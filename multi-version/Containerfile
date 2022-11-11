FROM docker.io/accetto/ubuntu-vnc-xfce-opengl-g3
USER root

RUN apt-get update && apt-get install -y git unzip ca-certificates

ADD blender-2.93 blender-2.93
ADD blender-3.0 blender-3.0
ADD blender-3.1 blender-3.1
ADD blender-3.2 blender-3.2
ADD blender-3.3 blender-3.3

ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
