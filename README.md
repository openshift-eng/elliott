
## Overview

This repository is designed to manage metadata and tooling related to OpenShift Container Platform (OCP) docker images.

OpenShift is delivered in two forms:
- OpenShift Origin: Completely open source (http://github.com/openshift/origin).
- OpenShift Container Platform (OCP): Red Hat's enterprise offering of OpenShift.

Origin maintains several Dockerfiles directly in its GitHub repository. For example:
https://github.com/openshift/origin/tree/master/images/node - Builds the docker image that runs on all OpenShift Origin nodes.

For each docker image built by Origin, OCP builds a corresponding image. Ideally OCP would use the exact same Dockerfile
as Origin for its images, but there are a few, necessary differences:

1. Between Origin and OCP, the name of OpenShift related RPMs can differ.
For example: https://github.com/openshift/origin/blob/fe4f72c2b8d931ccb2a419e927216f2dd8c59279/images/node/Dockerfile#L17 .
In this Dockerfile, the RPM 'origin-sdn-ovs' is called 'atomic-openshift-sdn-ovs' when built as OCP. Here is the same
Dockerfile for OCP (node the difference in RPM name):
http://dist-git.host.prod.eng.bos.redhat.com/cgit/rpms/openshift-enterprise-node-docker/tree/Dockerfile?h=rhaos-3.7-rhel-7&id=1a9270a21f25fbb0a75305df8581faf3869664de#n34
2. OCP images build from a RHEL base image instead of a Centos base image.
3. Various labels required by the OCP image building process.

Despite these differences, it is highly desirable for developers in Origin to only have to change a single Dockerfile
(the one for Origin) and rarely, if ever, need to consider the Dockerfile content for OCP. To accomplish this,
the enterprise-images repo contains metadata about how Dockerfiles from Origin should be modified in order to serve
as a Dockerfile for OCP.

Consider this image metadata file:
groups/openshift-3.7/openshift-enterprise-node-docker/config.yml

The file describes a series of changes that must be made to the Origin Dockerfile:
- Labels which should be added
- The base image which should be used
- The name of the image to build
- String substitutions which must be made to add an OCP specific RPM name

The OpenShift Image Tool (/oit) applies these changes to the Origin Dockerfiles during the build process and
stores the results in Red Hat distgit system: http://dist-git.host.prod.eng.bos.redhat.com/cgit/rpms/openshift-enterprise-node-docker/ .
All Red Hat images must be repositories in distgit.

## Why you may be here...

1. You need the Continuous Delivery team to build a new image as part of OCP.
Action: Just open an issue and assign Justin Pierce as the owner.

2. You need to make a change to an image built for OCP (e.g. changing the name of image built for OCP).
Action: Feel free to open a PR against the image metadata you want to change. Or just open an issue. In either case,
assigned Justin Pierce as the owner.


## Using oit

### Making changes to a group of distgit repos

Clone a group locally. A working directory will be created with all distgits.
`$ ./oit/oit.py [--user=ocp-build] --group openshift-3.7 --branch rhaos-3.7-rhel-7 distgits:clone`

This command will output the working-directory created for the operation (e.g. /tmp/oit-X.tmp).
Use that for the remaining commands.

Set the version and release for all images in the group, but do not push changes to distgit yet.
`$ ./oit/oit.py --working-dir /tmp/oit-X.tmp --group openshift-3.7 --branch rhaos-3.7-rhel-7 distgits:update-dockerfile --version=3.7.0 --release=0.999.0.0 -m "Bumping version" --no-push`

Run some custom modification script
`$ ./oit/oit.py --working-dir /tmp/oit-X.tmp --group openshift-3.7 --branch rhaos-3.7-rhel-7 distgits:foreach --no-push --message "my change" --cmd -- sed ..`

Push the commits
`$ ./oit/oit.py --working-dir /tmp/oit-X.tmp --group openshift-3.7 --branch rhaos-3.7-rhel-7 distgits:push`