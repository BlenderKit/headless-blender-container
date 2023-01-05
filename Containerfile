FROM docker.io/accetto/ubuntu-vnc-xfce-opengl-g3
USER root

RUN apt-get update && apt-get install -y git unzip ca-certificates

ADD 2.93 /home/headless/blenders/2.93
ADD 3.0 /home/headless/blenders/3.0
ADD 3.1 /home/headless/blenders/3.1
ADD 3.2 /home/headless/blenders/3.2
ADD 3.3 /home/headless/blenders/3.3
ADD 3.4 /home/headless/blenders/3.4

ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
