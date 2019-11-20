FROM fedora:30
LABEL name="elliott-dev" \
  description="Elliott development container image" \
  maintainer="OpenShift Automated Release Tooling (ART) Team <aos-team-art@redhat.com>"
RUN dnf install -y \
    # runtime dependencies
    krb5-workstation python-bugzilla-cli rsync docker \
    python2 python2-certifi python2-click python2-dockerfile-parse python2-koji \
    python2-pykwalify python2-pyyaml python2-bugzilla python2-requests \
    python2-requests-kerberos python2-pygit2 python2-future \
    python3-certifi python3-click python3-dockerfile-parse python3-koji \
    python3-pykwalify python3-pyyaml python3-bugzilla python3-requests \
    python3-requests-kerberos python3-pygit2 python3-future \
    # development dependencies
    gcc python2-devel python2-pip python2-typing pylint krb5-devel git \
    python3-devel python3-autopep8 python3-typing-extensions \
    # other tools
    bash-completion vim tmux procps-ng psmisc wget curl net-tools iproute \
  # Red Hat IT Root CA
  && curl -o /etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt --fail -L \
    https://password.corp.redhat.com/RH-IT-Root-CA.crt \
  && update-ca-trust extract \
  # clean up
  && dnf clean all

# install brewkoji
RUN wget -O /etc/yum.repos.d/rcm-tools-fedora.repo https://download.devel.redhat.com/rel-eng/RCMTOOLS/rcm-tools-fedora.repo \
  && dnf install -y koji brewkoji \
  && dnf install -y rhpkg \
  && dnf clean all

ARG OC_VERSION=4.2.4
#include latest oc client
RUN wget -O /tmp/openshift-client-linux-"$OC_VERSION".tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"$OC_VERSION"/openshift-client-linux-"$OC_VERSION".tar.gz \
  && tar -C /usr/local/bin -xzf  /tmp/openshift-client-linux-"$OC_VERSION".tar.gz oc kubectl \
  && rm /tmp/openshift-client-linux-"$OC_VERSION".tar.gz

# Create a non-root user - see https://aka.ms/vscode-remote/containers/non-root-user.
ARG USERNAME=dev
# On Linux, replace with your actual UID, GID if not the default 1000
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create the "dev" user
RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" -m "$USERNAME" \
    && mkdir -p /workspaces/elliott \
    && chown -R "${USER_UID}:${USER_GID}" /home/"$USERNAME" /workspaces/elliott \
    && chmod 0755 /home/"$USERNAME" \
    && echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME" \
    && chmod 0440 /etc/sudoers.d/"$USERNAME"

# Workaround for running `kinit` in an unprivileged container
# by storing krb5 credential cache into a file rather than kernel keyring.
# See https://blog.tomecek.net/post/kerberos-in-a-container/
ENV KRB5CCNAME=FILE:/tmp/krb5cache

USER "$USER_UID"
WORKDIR /workspaces/elliott
