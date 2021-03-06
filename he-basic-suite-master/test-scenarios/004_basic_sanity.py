# Copyright 2014-2019 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#
import os
from os import EX_OK
import nose.tools as nt
from nose import SkipTest

from ovirtsdk.xml import params

from lago import ssh
from ovirtlago import testlib
import ovirtsdk4 as sdk4
import ovirtsdk4.types as types

import test_utils
import uuid
from test_utils import ipv6_utils


MB = 2 ** 20
GB = 2 ** 30

TEST_DC = 'Default'
TEST_CLUSTER = 'Default'
TEMPLATE_BLANK = 'Blank'
TEMPLATE_CENTOS7 = 'centos7_template'

MANAGEMENT_NETWORK = 'ovirtmgmt'
VM0_NAME = 'vm0'
VM1_NAME = 'vm1'
DISK0_NAME = '%s_disk0' % VM0_NAME
DISK1_NAME = '%s_disk1' % VM1_NAME

SD_NFS_NAME = 'nfs'

SD_ISCSI_HOST_NAME = testlib.get_prefixed_name('storage')
SD_ISCSI_TARGET = 'iqn.2014-07.org.ovirt:storage'
SD_ISCSI_PORT = 3260
SD_ISCSI_NR_LUNS = 2
DLUN_DISK_NAME = 'DirectLunDisk'
VM_USER_NAME='cirros'
VM_PASSWORD='gocubsgo'

def _ping(ovirt_prefix, destination):
    """
    Ping a given destination.
    """
    host = ovirt_prefix.virt_env.host_vms()[0]
    cmd = ['ping', '-4', '-c', '1']
    ret = host.ssh(cmd + [destination])
    return ret.code


def _vm_ssh(ip_address, command, tries=None):
    return ssh.ssh(
        ip_addr=ip_address,
        command=command,
        username=VM_USER_NAME,
        password=VM_PASSWORD,
        tries=tries,
    )

def assert_vm0_is_alive(prefix):
    assert_vm_is_alive(prefix, test_utils.get_vm0_ip_address(prefix))


def assert_vm_is_alive(prefix, ip_address):
    testlib.assert_true_within_short(
        lambda:
        _ping(prefix, ip_address) == EX_OK
    )
    nt.assert_equals(_vm_ssh(ip_address, ['true']).code, EX_OK)


def setup_module():
    ipv6_utils.open_connection_to_api_with_ipv6_on_relevant_suite()


@testlib.with_ovirt_api4
def add_vm_blank(api):
    engine = api.system_service()
    vms_service = engine.vms_service()

    vm_memory = 512 * MB
    vm_params = sdk4.types.Vm(
        name=VM0_NAME,
        memory=vm_memory,
        os=sdk4.types.OperatingSystem(
            type='rhel_7x64',
        ),
        type=sdk4.types.VmType.SERVER,
        high_availability=sdk4.types.HighAvailability(
            enabled=False,
        ),
        cluster=sdk4.types.Cluster(
            name=TEST_CLUSTER,
        ),
        template=sdk4.types.Template(
            name=TEMPLATE_BLANK,
        ),
        display=sdk4.types.Display(
            smartcard_enabled=True,
            keyboard_layout='en-us',
            file_transfer_enabled=True,
            copy_paste_enabled=True,
            type=sdk4.types.DisplayType.SPICE
        ),
        usb=sdk4.types.Usb(
            enabled=True,
            type=sdk4.types.UsbType.NATIVE,
        ),
        memory_policy=sdk4.types.MemoryPolicy(
            ballooning=True,
            guaranteed=vm_memory / 2,
        ),
    )

    vms_service.add(vm_params)
    vm0_vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    testlib.assert_true_within_short(
        lambda: vm0_vm_service.get().status == sdk4.types.VmStatus.DOWN
    )


@testlib.with_ovirt_api4
def add_nic(api):
    NIC_NAME = 'eth0'
    # Locate the vnic profiles service and use it to find the ovirmgmt
    # network's profile id:
    profiles_service = api.system_service().vnic_profiles_service()
    profile_id = next(
        (
            profile.id for profile in profiles_service.list()
            if profile.name == MANAGEMENT_NETWORK
        ),
        None
    )

    # Empty profile id would cause fail in later tests (e.g. add_filter):
    nt.assert_is_not_none(profile_id)

    # Locate the virtual machines service and use it to find the virtual
    # machine:
    vms_service = api.system_service().vms_service()
    vm = vms_service.list(search='name=%s' % VM0_NAME)[0]

    # Locate the service that manages the network interface cards of the
    # virtual machine:
    nics_service = vms_service.vm_service(vm.id).nics_service()

    # Use the "add" method of the network interface cards service to add the
    # new network interface card:
    nics_service.add(
        types.Nic(
            name=NIC_NAME,
            interface=types.NicInterface.VIRTIO,
            vnic_profile=types.VnicProfile(
                id=profile_id
            ),
        ),
    )


@testlib.with_ovirt_api4
def add_disk(api):
    engine = api.system_service()
    vm0_service = test_utils.get_vm_service(engine, VM0_NAME)
    vm0_disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM0_NAME)

    vm0_disk_attachments_service.add(
        types.DiskAttachment(
            disk=types.Disk(
                name=DISK0_NAME,
                format=types.DiskFormat.COW,
                initial_size=10 * GB,
                provisioned_size=1,
                sparse=True,
                storage_domains=[
                    types.StorageDomain(
                        name=SD_NFS_NAME,
                    ),
                ],
            ),
            interface=types.DiskInterface.VIRTIO,
            active=True,
            bootable=True,
        ),
    )

    disk0_service = test_utils.get_disk_service(engine, DISK0_NAME)
    disk0_attachment_service = vm0_disk_attachments_service.attachment_service(disk0_service.get().id)

    testlib.assert_true_within_long(
        lambda:
        disk0_attachment_service.get().active == True
    )
    testlib.assert_true_within_long(
        lambda:
        disk0_service.get().status == types.DiskStatus.OK
    )


@testlib.with_ovirt_prefix
def add_directlun(prefix):
    luns = test_utils.get_luns(
        prefix, SD_ISCSI_HOST_NAME, SD_ISCSI_PORT, SD_ISCSI_TARGET, from_lun=SD_ISCSI_NR_LUNS+1)
    dlun_params = sdk4.types.Disk(
        name=DLUN_DISK_NAME,
        format=sdk4.types.DiskFormat.RAW,
        lun_storage=sdk4.types.HostStorage(
            type=sdk4.types.StorageType.ISCSI,
            logical_units=luns,
        ),
    )

    api = prefix.virt_env.engine_vm().get_api_v4()
    engine = api.system_service()
    disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM0_NAME)
    with test_utils.TestEvent(engine, 97):
        disk_attachments_service.add(sdk4.types.DiskAttachment(
            disk=dlun_params,
            interface=sdk4.types.DiskInterface.VIRTIO_SCSI))

        disk_service = test_utils.get_disk_service(engine, DLUN_DISK_NAME)
        attachment_service = disk_attachments_service.attachment_service(disk_service.get().id)
        nt.assert_not_equal(
            attachment_service.get(),
            None,
            'Failed to attach Direct LUN disk to {}'.format(VM0_NAME)
        )


@testlib.with_ovirt_api4
def snapshot_merge(api):
    engine = api.system_service()
    vm0_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM0_NAME)

    disk = engine.disks_service().list(search='name={}'.format(DISK0_NAME))[0]

    dead_snap1_params = types.Snapshot(
        description='dead_snap1',
        persist_memorystate=False,
        disk_attachments=[
            types.DiskAttachment(
                disk=types.Disk(
                    id=disk.id
                )
            )
        ]
    )

    correlation_id = uuid.uuid4()
    vm0_snapshots_service.add(
        dead_snap1_params,
        query={'correlation_id': correlation_id}
    )
    testlib.assert_true_within_short(
        lambda:
        test_utils.all_jobs_finished(engine, correlation_id)
    )
    testlib.assert_true_within_short(
        lambda:
        vm0_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK
    )

    dead_snap2_params = types.Snapshot(
        description='dead_snap2',
        persist_memorystate=False,
        disk_attachments=[
            types.DiskAttachment(
                disk=types.Disk(
                    id=disk.id
                )
            )
        ]
    )

    correlation_id_snap2 = uuid.uuid4()

    vm0_snapshots_service.add(
        dead_snap2_params,
        query={'correlation_id': correlation_id_snap2}
    )
    testlib.assert_true_within_short(
        lambda:
        test_utils.all_jobs_finished(engine, correlation_id_snap2)
    )
    testlib.assert_true_within_short(
        lambda:
        vm0_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK
    )

    snapshot = vm0_snapshots_service.list()[-2]
    vm0_snapshots_service.snapshot_service(snapshot.id).remove()
    testlib.assert_true_within_short(
        lambda:
        (len(vm0_snapshots_service.list()) == 2) and
        (vm0_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK),
    )


@testlib.with_ovirt_api
def add_vm_template(api):
    #TODO: Fix the exported domain generation
    raise SkipTest('Exported domain generation not supported yet')
    vm_params = params.VM(
        name=VM1_NAME,
        memory=512 * MB,
        cluster=params.Cluster(
            name=TEST_CLUSTER,
        ),
        template=params.Template(
            name=TEMPLATE_CENTOS7,
        ),
        display=params.Display(
            type_='spice',
        ),
    )
    api.vms.add(vm_params)
    testlib.assert_true_within_long(
        lambda: api.vms.get(VM1_NAME).status.state == 'down',
    )
    disk_name = api.vms.get(VM1_NAME).disks.list()[0].name
    testlib.assert_true_within_long(
        lambda:
        api.vms.get(VM1_NAME).disks.get(disk_name).status.state == 'ok'
    )


@testlib.with_ovirt_prefix
def vm_run(prefix):
    api = prefix.virt_env.engine_vm().get_api()
    host_names = [h.name() for h in prefix.virt_env.host_vms()]

    start_params = params.Action(
        vm=params.VM(
            placement_policy=params.VmPlacementPolicy(
                host=params.Host(
                    name=sorted(host_names)[0]
                ),
            ),
        ),
    )
    api.vms.get(VM0_NAME).start(start_params)
    testlib.assert_true_within_short(
        lambda: api.vms.get(VM0_NAME).status.state == 'up',
    )


@testlib.with_ovirt_prefix
def vm_migrate(prefix):
    api = prefix.virt_env.engine_vm().get_api()
    host_names = [h.name() for h in prefix.virt_env.host_vms()]

    migrate_params = params.Action(
        host=params.Host(
            name=sorted(host_names)[1]
        ),
    )
    api.vms.get(VM0_NAME).migrate(migrate_params)
    testlib.assert_true_within_short(
        lambda: api.vms.get(VM0_NAME).status.state == 'up',
    )


@testlib.host_capability(['snapshot-live-merge'])
@testlib.with_ovirt_api
def snapshot_live_merge(api):
    disk = api.vms.get(VM0_NAME).disks.list()[0]
    disk_id = disk.id
    disk_name = disk.name

    live_snap1_params = params.Snapshot(
        description='live_snap1',
        persist_memorystate=True,
        disks=params.Disks(
            disk=[
                params.Disk(
                    id=disk_id,
                ),
            ],
        ),
    )
    api.vms.get(VM0_NAME).snapshots.add(live_snap1_params)
    testlib.assert_true_within_short(
        lambda:
        api.vms.get(VM0_NAME).snapshots.list()[-1].snapshot_status == 'ok'
    )

    live_snap2_params = params.Snapshot(
        description='live_snap2',
        persist_memorystate=True,
        disks=params.Disks(
            disk=[
                params.Disk(
                    id=disk_id,
                ),
            ],
        ),
    )
    api.vms.get(VM0_NAME).snapshots.add(live_snap2_params)
    for i, _ in enumerate(api.vms.get(VM0_NAME).snapshots.list()):
        testlib.assert_true_within_short(
            lambda:
            (api.vms.get(VM0_NAME).snapshots.list()[i].snapshot_status
             == 'ok')
        )

    api.vms.get(VM0_NAME).snapshots.list()[-2].delete()

    testlib.assert_true_within_long(
        lambda: len(api.vms.get(VM0_NAME).snapshots.list()) == 2,
    )

    for i, _ in enumerate(api.vms.get(VM0_NAME).snapshots.list()):
        testlib.assert_true_within_long(
            lambda:
            (api.vms.get(VM0_NAME).snapshots.list()[i].snapshot_status
             == 'ok'),
        )
    testlib.assert_true_within_short(
        lambda: api.vms.get(VM0_NAME).status.state == 'up'
    )

    testlib.assert_true_within_long(
        lambda:
        api.vms.get(VM0_NAME).disks.get(disk_name).status.state == 'ok'
    )


@testlib.with_ovirt_prefix
def hotplug_nic(prefix):
    raise SkipTest('https://bugzilla.redhat.com/1776317')
    api = prefix.virt_env.engine_vm().get_api_v4()
    vms_service = api.system_service().vms_service()
    vm = vms_service.list(search='name=%s' % VM0_NAME)[0]
    nics_service = vms_service.vm_service(vm.id).nics_service()
    nics_service.add(
        types.Nic(
            name='eth1',
            interface=types.NicInterface.VIRTIO
        ),
    )
    assert_vm0_is_alive(prefix)


@testlib.with_ovirt_api
def hotplug_disk(api):
    disk2_params = params.Disk(
        name=DISK1_NAME,
        size=10 * GB,
        provisioned_size=1,
        interface='virtio',
        format='cow',
        storage_domains=params.StorageDomains(
            storage_domain=[
                params.StorageDomain(
                    name='nfs',
                ),
            ],
        ),
        status=None,
        sparse=True,
        bootable=False,
    )
    api.vms.get(VM0_NAME).disks.add(disk2_params)
    testlib.assert_true_within_short(
        lambda:
        api.vms.get(VM0_NAME).disks.get(DISK1_NAME).status.state == 'ok'
    )


_TEST_LIST = [
    add_vm_blank,
    add_nic,
    add_disk,
    snapshot_merge,
    add_vm_template,
    add_directlun,
    vm_run,
    vm_migrate,
    snapshot_live_merge,
    hotplug_nic,
    hotplug_disk,
]


def test_gen():
    for t in testlib.test_sequence_gen(_TEST_LIST):
        test_gen.__name__ = t.description
        yield t
