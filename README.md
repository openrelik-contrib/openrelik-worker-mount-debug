# OpenRelik worker mount debugging

This container can be used to debug disk imaging mounting workflows. The container will run several tools against the image, display its output and try to setup and mount the disk image. This can useful for debugging or analyzing different disk image formats and filesystem formats supported by OpenRelik.

## Prerequisites
The container needs to run privleged and have the /dev folder mounted into the container.

The container and mount code will use the following tools:
* losetup
* qemu-nbd
* fdisk
* lsblk
* blkid
* mount

## Configuration
Add below to your docker compose file.
```
openrelik-worker-mount-debug:
        container_name: openrelik-worker-mount-debug
        image: ghcr.io/openrelik/openrelik-worker-mount-debug:latest
        privileged: true
        restart: always
        environment:
          - REDIS_URL=redis://openrelik-redis:6379
        volumes:
          - ./data:/usr/share/openrelik/data
          - /dev:/dev
        command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=DEBUG -Q openrelik-worker-mount-debug"
```