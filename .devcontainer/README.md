## Elliott Development Container Support for VSCode

This directory contains the `Dockerfile` and `devcontainer.json` file
that allows you to develop and debug `elliott` inside a development container
using Visual Studio Code. See [https://code.visualstudio.com/docs/remote/containers]() for more information.

## Quick Start

1. Install the [Remote Development Extension Pack][] on Visual Studio Code.
2. Open `elliott` project locally.
3. If you are using Linux, make sure the `USER_UID` `USER_GID` arguments in `dev.Dockerfile` match your actual UID and GID. Ignore this step if you are using macOS or Windows.
4. Click the green icon on the bottom left of the VSCode window or press <kbd>F1</kbd>, then choose `Remote-Containers: Reopen in Container`.

[Remote Development Extension Pack]: https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.vscode-remote-extensionpack

# Development container use with podman 
    
The same Dockerfile can be used independently to provide a doozer environment container.
A build with podman may look like:
    
    USERNAME=yours
    USER_UID=1234
    podman build --build-arg USERNAME=$USERNAME --build-arg USER_UID=$USER_UID \
                 -f .devcontainer/dev.Dockerfile -t local/elliott .
    
Then a script similar to the following (you will certainly want your own modifications)
will run the container, mounting in relevant things from your own user directory to be
accessible to the same user inside the container.
    
#!/bin/bash
 
    USER=yours
    # location of elliott checkout
    ELLIOTT="$HOME/openshift/elliott"
    CONTAINER="$ELLIOTT/.devcontainer"
  
    # make a copy of your kerberos credentials to mount in (if you mount in the original,
    # the selinux labels are changed and kerberos refuses to update it).
    cp -a "${KRB5CCNAME#FILE:}"{,_elliott}

    # mounting in your .ssh dir changes selinux labels, preventing sshd from logging
    # your user in remotely; make a copy and mount that instead if needed.
    rm -rf $HOME/.ssh_elliott
    cp -a $HOME/.ssh{,_elliott}

    # you'll likely have to modify uidmap according to your own user's uid range.
    # for 1234 below of course substitute your own UID.
    podman run -it --rm \
        --uidmap 0:10000:1000 --uidmap=1234:0:1 \
        -v "${KRB5CCNAME#FILE:}_elliott":/tmp/krb5cc_1234:ro,z \
        -v $DOOZER:/workspaces/elliott:cached,z \ 
        -v $HOME/.ssh_elliott:/home/$USER/.ssh:ro,cached,z \
        -v $HOME/.gitconfig:/home/$USER/.gitconfig:ro,cached,z \
        -v $HOME/.docker:/home/$USER/.docker:ro,cached,z  \
        -v $CONTAINER/settings.yaml:/home/$USER/.config/elliott/settings.yaml:ro,cached,z \
        -v $CONTAINER/krb5-redhat.conf:/etc/krb5.conf.d/krb5-redhat.conf:ro,cached,z \
        -v $CONTAINER/brewkoji.conf:/etc/koji.conf.d/brewkoji.conf:ro,cached,z \
        local/elliott

