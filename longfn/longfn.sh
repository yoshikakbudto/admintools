#!/bin/bash
#
# UTF-8
#       comments in russian
#       messages in english
#
# ДЛЯ ЧЕГО ЭТО
# Ищет файлы с длинной имени не влезающей на encfs. 
# При желании, укорачивает.
#   - Макс.кол-во байт в имени: 143 (проверено эмпирически для encfs)
#   - eng символы идут по 1 байт за каждый
#   - рус символы по 2 байта.
#     проверить можно просто скормив имя файла в wc -c
#     Т.е. в худшем случае c полностью рус.символами максимум: 71
#
# ИСПОЛЬЗОВАНИЕ
#  longfn.sh <список путей> <флаг_переименовывать_файлы>
#
# ПРИМЕР 
#  longfn.sh "/var/mgmt
#            #/backup/blog
#     $1:    /var/mgmt_personal
#     $2:    "true"
#set -x
# \x5b is needed by jelly template to not echo the script sctring (on server: /var/lib/jenkins/email-templates/)
scan_dirs="$1"
squeeze_fn=${2:-false}

fname_max_chars=143

echo -e "\n\n
****************************************************************************************
*  Searching for the file names above EncFs limit of ${fname_max_chars} bytes
*  the number in square brackets - is the file name size in bytes
****************************************************************************************
"
echo "${scan_dirs}" |  grep -Ev "(^#)|(^$)" | \
{ found="";
  while read path; do
        sudo find "${path}" -regextype posix-extended -regex '.*/[^/]{70,}'  \
             | {  found="";
                  while read str; do
                        dir=$(dirname "$str");
                        fn=$(basename "$str");
                        name_size=$(echo ${fn} | wc -c);
                        [ ${name_size} -gt ${fname_max_chars} ] && {
                            echo -e "\x5bfound][${name_size}] ${str}"
                            ( ${squeeze_fn} )&& {
                                nfn="${fn:0:60}...${fn: -7}";
                                sudo mv --force "${str}" "${dir}/${nfn}" && 
                                      echo -e "\x5brenamed] ${nfn}" || 
                                       echo -e "\x5brename failed] ${nfn}"                                        
                            }
                            found=yep;
                        }
                  done;
                 [ "$found" ]&& exit 1;
                 exit 0
               }
   [ $? -ne 0 ]&& found=yep
   done;
 [ "$found" ] || echo "No files found."
 echo -e "\n****************************************************************************************\n\n"
 [ "$found" ]&& exit 1;
 exit 0;
}