FROM fedora:30

RUN dnf install -y python2 python2-pip krb5-workstation \
    gcc python2-devel krb5-devel python2-rpm redhat-rpm-config \
    bash-completion pylint python3-autopep8 git vim tmux procps-ng psmisc wget curl net-tools iproute \
  && curl -o /etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt --fail -L \
    https://password.corp.redhat.com/RH-IT-Root-CA.crt \
  && update-ca-trust extract \
  && dnf clean all

# Create a non-root user - see https://aka.ms/vscode-remote/containers/non-root-user.
ARG USERNAME=dev
# On Linux, replace with your actual UID, GID if not the default 1000
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create the "dev" user
RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" -m "$USERNAME" \
    && mkdir -p /home/"$USERNAME"/.vscode-server /home/"$USERNAME"/.vscode-server-insiders \
    && chown -R "${USER_UID}:${USER_GID}" /home/"$USERNAME" \
    && echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME" \
    && chmod 0440 /etc/sudoers.d/"$USERNAME"

# Configure Kerberos
COPY .devcontainer/krb5-redhat.conf /etc/krb5.conf.d/
# Workaround for running `kinit` in an unprivileged container
# by storing krb5 credential cache into a file rather than kernel keyring.
# See https://blog.tomecek.net/post/kerberos-in-a-container/
ENV KRB5CCNAME=FILE:/tmp/krb5cache

# Set the default user
USER $USERNAME
ENV ELLIOTT_DATA_PATH=https://gitlab.cee.redhat.com/openshift-art/ocp-build-data.git
