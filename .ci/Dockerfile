FROM centos:7

RUN yum install -y epel-release gcc krb5-devel python-devel
RUN yum install -y python-pip
RUN pip install tox

ENV PYTHONDONTWRITEBYTECODE 1
ENTRYPOINT ["tox"]
