#!/bin/bash

export MAJOR_RELEASE="$1"
source "$2"

assoc2json() {
    declare -n v=$1
    printf '%s\0' "${!v[@]}" "${v[@]}" |
    jq -Rs 'split("\u0000") | . as $v | (length / 2) as $n | reduce range($n) as $idx ({}; .[$v[$idx]]=$v[$idx+$n])'
}

echo '{' # begin file

echo '  "dict_image_type": '
assoc2json dict_image_type
echo ','

echo '  "dict_image_from": '
assoc2json dict_image_from
echo ','

echo '  "dict_git_compare": '
assoc2json dict_git_compare
echo ','

echo '  "dict_image_name": '
assoc2json dict_image_name
echo ','

echo '  "dict_image_tags": '
assoc2json dict_image_tags

echo '}' # end file
