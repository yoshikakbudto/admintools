#!/usr/bin/env bash
#
# UTF-8
#       comments in russian
#       messages in english
#
# ДЛЯ ЧЕГО ЭТО
# Для синхронизации кучки каталогов в удаленное хранилище по rsync
#
# ЛОГИКА РАБОТЫ
#      Если какой-то ресурс незасинкался, установить флаг и продолжить
#
# ИСПОЛЬЗОВАНИЕ
#  pathsync <список исходных каталогов и сообразных каталогов назначений\
#           <список шаблонов исключений для rsync, разделенный enter>\
#           <общие опции для rsync>\
#           <удаленный ssh сервер, можно в формате user@serv.ltd>
#           [sudo_rsync] запускать ли rsync под sudo
#           
# ПРИМЕР 
#  pathsync "/var/backup/dump/   /volume1/backups/system/vm/
#            #/backup/blog        /volume1/backups/office/ 
#     $1:    /var/backup/jenkins /volume1/backups/system/ 
#            /var/backup/certs   /volume1/backups/office/" \
#     $2:    "*.~
#            *.bak"\
#     $3:    "-rth --stats -exclude-from - --delete-excluded" \
#     $4:    "duser@remotessh.tld"
#     $5:    "" or sudo
#set -x
SRC_PATHS="$1"
RSYNC_EXCLUDE_LIST="$2"
STG_RSYNC_OPT="$3"
REMOTE_SSH_ADDR="$4"

if [ "$5" == "sudo_rsync" ]; then
    SUDO_RSYNC=sudo
else
    SUDO_RSYNC=""
fi



#----------------------------------------------------------------------------
# Если есть этот флаг, удалить. нужен для расчета оставшегося лимита Гб
#   В скрипте провизинга ВМ
#----------------------------------------------------------------------------
mb_provision_remain_fileflag=.vm_mb_per_run.~


#----------------------------------------------------------------------------
# FUNCTION: df_remote
#  purpose: выполнить df по ssh
#      in:  $1: user@ssh.remote.host.tld
#         [$2]: /remote/path (optional)
#     out:  df -Ph
#----------------------------------------------------------------------------
df_remote(){
  [ $# -lt 1 ]&&{ 
       echo "func()usage: $FUNCNAME user@ssh.remote.host.tld [/remote/path]";
       return 1;
  }

  echo "----------------------- [ remote fs space usage ]-----------------------"
  ssh -o BatchMode=yes \
      -o Compression=no \
      -o StrictHostKeyChecking=no \
      -o VerifyHostKeyDNS=yes\  $1 "df -Ph $2"
  echo "-----------------------------------------------------------------------"
}



################################################################################
#  MAIN
#
################################################################################

#----------------------------------------------------------------------------
# список каталожных пар скармливается в цикле в переменную, 
#  переменная с помощью средств bash разбирается на составные части, 
#  которые подставляются rsync в качетсве SRC и DST каталогов
#  cписок исключений скармливается в rsync через пайп в параметр "-exclude-from -"
#----------------------------------------------------------------------------
echo "

*********************************************************************
* Syncing paths from $(hostname) //user:${USER}
**********************************************************************"
echo "${SRC_PATHS}" | grep -Ev "(^#)|(^$)" \
   |{ unset no_sync_err;
      while read i; do {
        echo -e "\n[INFO] ${i/ / => } ...";
        echo "${RSYNC_EXCLUDE_LIST}" \
           | ${SUDO_RSYNC} rsync ${STG_RSYNC_OPT} --update \
                 --rsh='/usr/bin/ssh -c aes128-ctr,aes128-cbc -x -o BatchMode=yes -o Compression=no  -o StrictHostKeyChecking=no -o VerifyHostKeyDNS=yes' \
                 --out-format='[%o] %i %n%L (%l bytes)' \
                 --rsync-path='/opt/bin/rsync' \
                 ${i%%[[:blank:]]*} ${REMOTE_SSH_ADDR}:${i##*[[:blank:]]}
                _ecd=$?;
                echo rsync exited with: ${_ecd}
             [ ${_ecd} -ne 0 ] && {
               no_sync_err+="[ERROR] some shit happened while syncing ${i/ / => }\n";
             } || { 
               rm -vf ${i%%[[:blank:]]*}/${mb_provision_remain_fileflag};
             };
      }; done;
      df_remote ${REMOTE_SSH_ADDR}
      [ "${no_sync_err}" ] &&  echo -e "\n\n${no_sync_err}" && exit 1;
      exit 0;
    }
exit $?