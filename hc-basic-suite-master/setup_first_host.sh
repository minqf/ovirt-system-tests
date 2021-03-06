#!/usr/bin/env bash
yum install -y --nogpgcheck ovirt-engine-appliance
yum install -y ansible gluster-ansible-roles ovirt-ansible-hosted-engine-setup ovirt-ansible-repositories ovirt-ansible-engine-setup
rm -rf /var/cache/yum/* /var/cache/dnf/*

#DISK_DEV=disk/by-id/0QEMU_QEMU_HARDDISK_4
DISK_DEV=sdc

mkfs.xfs -K /dev/${DISK_DEV}
mount /dev/${DISK_DEV} /var/tmp
echo -e '/dev/${DISK_DEV}\t/var/tmp\t\t\txfs\tdefaults\t0 0' >> /etc/fstab


