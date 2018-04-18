#!/bin/bash

# Invoke using something like:
# ./oit.py --user ocp-build --working-dir play --group openshift-3.10 images:foreach $(pwd)/hack/util/rpm_printit.sh

if [[ -z "${oit_image_name}" ]]; then
	echo "Expected environment variable!"
	exit 1
fi

echo "repo: ${oit_repo_name}"
# echo "${oit_group}"
# echo "${oit_working_dir}"
# echo "${oit_metadata_dir}"
docker run --entrypoint /bin/sh --user root -it registry.reg-aws.openshift.com:443/${oit_image_name}:${oit_image_version} -c "rpm -q \$(yum history info | grep 'Install ' | grep ose | tr -s ' ' | cut -d ' ' -f 3) --qf '%{NAME}\n' "
