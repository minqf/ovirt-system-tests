#
# Copyright 2020 Red Hat, Inc.
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

from __future__ import absolute_import

import contextlib
import logging

from ost_utils.selenium import CHROME_CONTAINER_IMAGE
from ost_utils.selenium import FIREFOX_CONTAINER_IMAGE
from ost_utils.selenium import HUB_CONTAINER_IMAGE
from ost_utils.selenium import common
from ost_utils.shell import shell


HUB_IP = "127.0.0.1"
HUB_PORT = 4444
LOGGER = logging.getLogger(__name__)
NODE_PORT_GEN = iter(range(5600, 5700))
NODE_DISPLAY_ADDR_GEN = iter(range(100, 200))


def _log_issues(hub_name, node_names):
    LOGGER.error("Hub logs: \n%s" % shell(["podman", "logs", hub_name]))
    for name in node_names:
        LOGGER.error(
            "Node %s logs: \n%s" % (name, shell(["podman", "logs", name]))
        )


@contextlib.contextmanager
def _pod(hub_port):
    name = shell(["podman", "pod", "create", "-p", str(hub_port)]).strip()
    try:
        yield name
    finally:
        shell(["podman", "pod", "rm", name])


@contextlib.contextmanager
def _hub(image, pod_name):
    name = shell(["podman", "run", "-d", "--pod", pod_name, image]).strip()
    try:
        yield name
    finally:
        shell(["podman", "rm", "-f", name])


# When running multiple containers in a pod, they compete over
# resources like network ports. This is why we can't simply run
# multiple selenium nodes in a single pod - we need to change
# the ports they're using by default and the 'DISPLAY' variable
# (we're using debug images which run VNC server) to some unique
# values.
@contextlib.contextmanager
def _nodes(images, hub_port, pod_name, engine_dns_entry):
    names = []

    for image in images:
        name = shell([
            "podman", "run", "-d",
            "--add-host={}".format(engine_dns_entry),
            "-e", "HUB_HOST={}".format(HUB_IP),
            "-e", "HUB_PORT={}".format(hub_port),
            "-e", "SE_OPTS=-port {}".format(next(NODE_PORT_GEN)),
            "-e", "DISPLAY=:{}".format(next(NODE_DISPLAY_ADDR_GEN)),
            "--pod", pod_name,
            image
        ]).strip()
        names.append(name)

    try:
        yield names
    finally:
        for name in names:
            shell(["podman", "rm", "-f", name])


@contextlib.contextmanager
def grid(engine_fqdn, engine_ip, node_images=None,
         hub_image=HUB_CONTAINER_IMAGE, hub_port=HUB_PORT):
    if node_images is None:
        node_images = [CHROME_CONTAINER_IMAGE, FIREFOX_CONTAINER_IMAGE]

    engine_dns_entry="{}:{}".format(engine_fqdn, engine_ip)

    with common.http_proxy_disabled():
        with _pod(hub_port) as pod_name:
            with _hub(hub_image, pod_name) as hub_name:
                with _nodes(node_images, hub_port, pod_name,
                            engine_dns_entry) as node_names:
                    url = common.GRID_URL_TEMPLATE.format(HUB_IP, hub_port)
                    try:
                        common.grid_health_check(url, len(node_images))
                    except RuntimeError:
                        _log_issues(hub_name, node_names)
                        raise
                    yield url
