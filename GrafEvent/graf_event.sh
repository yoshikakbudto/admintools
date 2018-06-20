#!/bin/bash
# v0.1
# Впузыривалка док в ES для ивентов графаны эндКо.
# 
# Зависимости: curl
#
#
#
#-------------------------------------------------------------------- 
# functions go further
#--------------------------------------------------------------------
show_help(){
   cat <<-EOF
 
  Usage: `basename $0` 
            -H|--title <event title>                  - At least this must be set
           [-T|--timestamp <UTC timestamp>]           - YYYY-MM-DDTHH:MM:SS.SSS  Default: now
           [-t|--tags  <tag1[,tag2][,tagN]...]        - one or more tags. Default: "sc"
           [-i|--index <elastic index name>]          - Default:  "events-dev"
           [-D|--desc  <event description>]           - Default: "it happens"
           [-d|--docum <index document> ]             - Default: prod
           [-S|--host <elasticsearch server addr>]    - Default: web.domain.tld:9200
           [-h|--help]

  EXAMPLE:
  create an event document in default index for future datacenter maintanance:
       `basename $0` -T 2015-09-10T05:00:00.000 -t sc,dc,planned -H "US datacenter mnt begin" 
       `basename $0` -T 2015-09-10T10:00:00.000 -t sc,dc,planned -H "US datacenter mnt end" 


EOF
}





#-init_vars--------------------------------------------------------------------
# purpose:    Проверить и нормализовать значения в переменных ком.строки
#              определить глобальные переменные
#     out:  --
#      in:  --
#------------------------------------------------------------------------------
do_init(){
  #----------------------------------------
  # Проверка доступности зависимостей
  #----------------------------------------
  deps="sed grep curl cat"
  unset failed_deps
  for i in ${deps};do
      command -v $i &>/dev/null || failed_deps+="$i "
  done
  [ "$failed_deps" ] &&
       { echo -e "\n[ERROR] these deps aren't on the PATH: $failed_deps"; exit 1; };
       
  # просто 'dirname $0' не всегда работает, если скрипт пускался с относит.путем
  [ "${0:0:1}" = "/" ] && my_base_path=$(dirname $0) || my_base_path=$PWD

  getopt -o i:T:t:H:D:d:S:h --long help,index:,timestamp:,tags:,title:,desc:,host:,docum: -- "$@" || exit 1
 
  while [ ! -z "$1" ];
  do
    case $1 in
         -i|--index)
            index=$2; shift 2;
         ;;
         -T|--timestamp)
            timestamp=$2; shift 2;
         ;;
         -t|--tags)
            tags=$2; shift 2;
         ;;
         -H|--title)
            title=$2; shift 2;
         ;;
         -S|--host)
            host=$2; shift 2;
         ;;
         -d|--docum)
            docum=$2; shift 2;
         ;;
         -D|--desc)
            desc=$2; shift 2;
         ;;
         -h|--help)
            show_help; exit 0;
         ;;
         *)
             echo "[ERROR] unknown option: '$1'"; 
             show_help; exit 1;
         ;;
    esac
  done

  # Имена (не значения) переменных обязательные для установки в ком.строке
  for must_be_set in title; do
      eval test -z \"\${$must_be_set}\"&&{ 
         echo -e "\n[ERROR] $must_be_set must be set";
         show_help; 
         exit 1;
      }
  done 

  #---------------------------------------------
  #  Установить переменные отталкиваясь от дефолтных значений
  #---------------------------------------------
  default_index=events-dev
  default_timestamp=$(date --utc +"%FT%T.%N" | cut -c-23);
  default_tags=deploy
  default_title="event"
  default_desc="it happens"
  default_host=technode01st-ru.domain.tld:9200
  default_docum=prod


  eval timestamp=\${timestamp:-${default_timestamp}};
  eval tags=\${tags:-${default_tags}};
  eval title=\${title:-${default_title}};
  eval desc=\${desc:-${default_desc}};
  eval index=\${index:-${default_index}};
  eval host=\${host:-${default_host}};
  eval docum=\${docum:-${default_docum}};

  (( ${#timestamp} <23 )) && {
    echo -e "\nERROR: timestamp variable has got wrong time format: \"${timestamp}\"";
    echo -e "should be something like: 2015-09-04T11:41:51.066\n";
    exit 1;
  }

  #-----------------------------------------------
  # Нормализовать теги для испoльзования в джейсоне
  #-----------------------------------------------
  # remove spaces
  tags=${tags// /};
  tags=[\"${tags//,/\",\"}\"]

  return 0
}



###############################################################################
# MAIN
###############################################################################
do_init "$@"

echo "[INFO] store event \"${title}\" @${timestamp} in ES index \"${index}\" tagged ${tags}"

curl --connect-timeout 30 --silent -XPOST ${host}/${index}/${docum}/ -d "{
    \"@timestamp\": \"${timestamp}\", 
    \"tags\" : ${tags}, 
    \"title\" : \"${title}\", 
    \"desc\" : \"${desc}\"
}"

exit
curl -XPOST ${el_port}/${el_idx}/${el_doc}/ -d "{
    "@timestamp": "${timestamp}", 
    "tags" : ["deploy", "sc"], 
    "title" : "deploy end", 
    "desc" : "Client deploy via steam,yuplay"
}"
