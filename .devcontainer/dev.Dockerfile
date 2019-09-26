FROM fedora:30

RUN dnf install -y \
    # runtime dependencies
    krb5-workstation python-bugzilla-cli \
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
    && chmod 0755 /home/"$USERNAME" \
    && echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME" \
    && chmod 0440 /etc/sudoers.d/"$USERNAME"

# Configure Kerberos
COPY .devcontainer/krb5-redhat.conf /etc/krb5.conf.d/
# Workaround for running `kinit` in an unprivileged container
# by storing krb5 credential cache into a file rather than kernel keyring.
# See https://blog.tomecek.net/post/kerberos-in-a-container/
ENV KRB5CCNAME=FILE:/tmp/krb5cache

# Configure elliott
ENV ELLIOTT_DATA_PATH=https://gitlab.cee.redhat.com/openshift-art/ocp-build-data.git \
  ELLIOTT_WORKING_DIR=/home/"$USERNAME"/elliott-working-dir

USER "$USER_UID"
