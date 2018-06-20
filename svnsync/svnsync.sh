#!/bin/sh
#
# UTF-8
#       comments in russian
#       messages in english
#
# ДЛЯ ЧЕГО ЭТО
#-Для синхронизации SVN в удаленное хранилище через svnsync. 
# - Используется ssh c авторизацией по ключу. В том числе для ssh-туннеля svnsync
# - Список исходных репоизиториев хранится в передаваемой перемнной
# - Если в удаленном хранилище репозиторий отсутствует, он будет создан автоматически
# - Для сокращения сетевого i/o используется файл-флаг состояния в каталоге с репой 
#
# НЕОЧЕВИДНЫЕ ТРЕБОВАНИЯ И ЗАВИСИМОСТИ
# - svnseve 1.8.x (в удаленном хранилище версия не ниже источника)
# - находимость в PATH svnserve через интерактивный ssh на удаленном хоесте. (ssh remotehost.ltd "svnserve -h")
# - у ssh клиента  должен быть правильный приватный ключ по дефолту. 
#   альтернативный можно указать ключом (обычно -i) в переменной перед именем сервера
# - выданы права внутри SVN для синхронизирующей ssh-учетки (conf/authz)
#
# ИСПОЛЬЗОВАНИЕ
#  svnsync.sh <список каталогов с репозиториями, разделенных ENTER>\
#             <SSH ревизиты>\
#             <путь хранения репозиториев в удаленном хранилище>\
#	      <полный путь к шаблону в удаленном хранилище>
#           
#  Примеры значений переменных в параметрах ком.строки:
#SVN_SRC_PATHS="#/home/svn/svnproject1
#/home/svn/svnproject2
#/home/svn/svnproject3"
#
#REMOTE_SSH_ADDR=sshuser@cloud.domaint.tld
#REMOTE_SVN_ROOT_PATH=/backups/svn
#REMOTE_SVN_INIT_TPL=/backups/svn/empty-repo-tpl

#set -x
SVN_SRC_PATHS="$1"
REMOTE_SSH_ADDR="$2"
REMOTE_SVN_ROOT_PATH="$3"
REMOTE_SVN_INIT_TPL="$4"

STAT_FILE=.synced-${REMOTE_SSH_ADDR}.~


# FUNCTION: df_remote
#  purpose: выполнить df по ssh
#      in:  $1: user@ssh.remote.host.tld
#           $2: /remote/path
#     out:  df -Ph
#----------------------------------------------------------------------------
df_remote(){
  [ $# -lt 2 ]&&{ 
       echo "func()usage: $FUNCNAME user@ssh.remote.host.tld /remote/path";
       return 1;
  }

  echo "----------------------- [ remote fs space usage ]-----------------------"
  ssh -o BatchMode=yes \
      -o Compression=no \
      -o StrictHostKeyChecking=no \
      -o VerifyHostKeyDNS=yes\  $1 "df -Ph $2"
  echo "-----------------------------------------------------------------------"
}


echo "
***************************************************************
* SYNCING SVN REPOS
***************************************************************"
######################################################################################################
# ПРОВЕРКИ И ИНИЦИАЦИЯ НЕСУЩЕСТВУЮЩИХ РЕП. В УДАЛЕННОМ ХРАНИЛИЩЕ
######################################################################################################
# Сохранить в переменную список каталогов с "репозиториями SVN" в удаленном хранилище. 
#                        (без проверки на их причастность к SVN)
#
echo "[INFO] getting remote repos: ssh ${REMOTE_SSH_ADDR} \"ls ${REMOTE_SVN_ROOT_PATH}\""
REMOTE_LS=$(ssh ${REMOTE_SSH_ADDR} "ls ${REMOTE_SVN_ROOT_PATH}") || exit $?

#
# Выполнить проверки:
# - Существуют ли все указанные "репозитории" в источнике (без проверки их валидности)
# Выполнить действия:
# - Если репозитторий не существует в удаленном хранилище, проверить на валидность репозитори источника
#        и создать из шаблона пустую репу
#
echo [INFO] checking source directories exist, finding a missing one at remote....
echo "${SVN_SRC_PATHS}" | grep -Ev "(^#)|(^$)" | while read i; do ls -d "$i" || exit $?; done |\
 	egrep -wv "$REMOTE_LS"| while read i; do {
		REPO=$(basename $i);
		echo "[WARN] ${REPO} not found at remote. Initializing a new one ...";
		echo -n "[INFO] Check repository valididy with its owner: ";
		svnlook author $i || exit $?;
		echo "[INFO] execute at remote: cp -pR ${REMOTE_SVN_INIT_TPL} ${REMOTE_SVN_ROOT_PATH}/${REPO}";
		ssh ${REMOTE_SSH_ADDR} "cp -pR ${REMOTE_SVN_INIT_TPL} ${REMOTE_SVN_ROOT_PATH}/${REPO}" || exit $?;
		echo "[INFO] initializing remote repository for svnsync..."
		svnsync init --allow-non-empty --non-interactive svn+ssh://${REMOTE_SSH_ADDR}${REMOTE_SVN_ROOT_PATH}/${REPO} file://$i; 
		}; done
echo [INFO] All checks done. continue...


#---------------------------------------------------------------------------------------
# Синхронизация изменений
# Если какую-то репу не смогли засинкать, сохранить статус ошибки и перейти к след.репе
#---------------------------------------------------------------------------------------
echo "${SVN_SRC_PATHS}" \
    |grep -Ev "(^#)|(^$)" \
        |{ unset no_sync_err;
           while read i; 
           do 
             REPO=$(basename $i);
             if [ ! -r $i -o ! -w $i -o ! -x $i ]; then 
               no_sync_err+="[ERROR] user $USER must have a write permission to $i\n";
               continue;
             fi

             if [ -f $i/${STAT_FILE} -a ! -w $i/${STAT_FILE} ]; then 
               no_sync_err+="[ERROR] user $USER must have a write permission to $i/${STAT_FILE}\n";
               continue;
             fi

             REPO_STATE=$(svnlook youngest $i);

             if ( ! echo "${REPO_STATE}" | cmp -s $i/${STAT_FILE} - );then
                 echo "[INFO] syncing $REPO up to revision $(svnlook youngest $i)";
                 svnsync sync --non-interactive --steal-lock --trust-server-cert \
                         svn+ssh://${REMOTE_SSH_ADDR}${REMOTE_SVN_ROOT_PATH}/${REPO} file://$i
                 [ $? -ne 0 ] && {
                   no_sync_err+="[ERROR] some shit happened while svnsyncing $REPO\n";
                   continue;
                 }
                 echo "${REPO_STATE}" > $i/${STAT_FILE};
             else
                 echo "[INFO] Skip syncing ${REPO} because of nothing new."
             fi
          done

        [ "${no_sync_err}" ] &&  echo -e "\n\n${no_sync_err}" && exit 1;
        exit 0;
        }

# вывести статистику по df если не было ошибок
[ $? -eq 0 ] && df_remote ${REMOTE_SSH_ADDR} ${REMOTE_SVN_ROOT_PATH}
exit