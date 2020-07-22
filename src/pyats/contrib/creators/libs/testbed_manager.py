import logging
import argparse
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from genie.conf.base import Testbed, Device, Interface, Link
from pyats.async_ import pcall

log = logging.getLogger(__name__)


class TestbedManager(object):
    '''Class designed to handle device interactions for connecting devcices
       and cdp and lldp
    '''
    def __init__(self, testbed, config=False, ssh_only=False, alias_dict={},
                 timeout=10, supported_os = ['nxos','iosxe', 'iosxr', 'ios']):

        self.config = config
        self.ssh_only = ssh_only
        self.testbed = testbed
        self.alias_dict = alias_dict
        self.timeout = timeout
        self.supported_os = supported_os
        self.cdp_configured = set()
        self.lldp_configured = set()
        self.visited_devices = set()


    def connect_all_devices(self, limit):
        '''Creates a ThreadPoolExecutor designed to connect to each device in

        Args:
            limit = max number of threads to spawn

        Returns:
            Dictionary of devices containing their connection status
        '''

        # Set up a thread pool executor to connect to all devices at the same time
        with ThreadPoolExecutor(max_workers = limit) as executor:
            for device_name, device_obj in self.testbed.devices.items():
                # If already connected or device has already been visited skip 
                if device_obj.connected or device_obj.os not in self.supported_os or device_name in self.visited_devices:
                    continue
                log.info('Attempting to connect to {device}'.format(device=device_name))
                executor.submit(self._connect_one_device,
                                device_name)

    def _connect_one_device(self, device):
        '''Connect to the given device in the testbed using the given
        connections and after that enable cdp and lldp if allowed

        Args:
            device: name of device being connected
        '''

        # if there is a prefered alias for the device, attempt to connect with device
        # using that alias, if the attmept fails or the alias doesn't exist, it will
        # attempt to connect normally
        if device in self.alias_dict:
            if self.alias_dict[device] in self.testbed.devices[device].connections:
                log.info('Attempting to connect to {} with alias {}'.format(device, self.alias_dict[device]))
                try:
                    self.testbed.devices[device].connect(via = str(self.alias_dict[device]),
                                                    connection_timeout = 10)
                except:
                    log.info('Failed to connect to {} with alias {}'.format(device, self.alias_dict[device]))
                    self.testbed.devices[device].destroy()
            else:
                log.info('Device {} does not have a connection with alias {}'.format(device, self.alias_dict[device]))

        if self.testbed.devices[device].connected:
            return

        for one_connect in self.testbed.devices[device].connections:
            if not self.ssh_only or (self.ssh_only and one_connect.protocol == 'ssh'):
                try:
                    self.testbed.devices[device].connect(via = str(one_connect),
                                                    connection_timeout = self.timeout)
                    break
                except Exception:
                    # if connection fails, erase the connection from connection mgr
                    self.testbed.devices[device].destroy()

    def configure_testbed_cdp_protocol(self):
        ''' Method checks if cdp configuration is necessary for all devices in
        the testbed and if needed calls the cdp configuration method for the
        target devices in parallel
        '''
        device_to_configure = []
        for device_name, device_obj in self.testbed.devices.items():
            if device_name in self.visited_devices or device_name in self.cdp_configured or not device_obj.connected:
                continue
            device_to_configure.append(device_obj)
        if not device_to_configure:
            return
        pcall(self.configure_device_cdp_protocol,
              device= device_to_configure)
        
            
    def configure_device_cdp_protocol(self, device):
        '''If allowed to edit device configuration enable cdp on the device 
        if it is disabled and then marks that configuration was done

        Args:
            device: the device having cdp enabled
        '''
        if not device.api.verify_cdp_in_state(max_time= self.timeout, check_interval=5):
            try:
                device.api.configure_cdp()
                self.cdp_configured.add(device.name)
            except Exception:
                log.error("Exception configuring cdp "
                            "for {device}".format(device = device.name),
                                                exc_info = True)
            
    
    def configure_testbed_lldp_protocol(self):
        ''' Method checks if lldp configuration is necessary for all devices in
        the testbed and if needed calls the cdp configuration method for the
        target devices in parallel
        '''
        device_to_configure = []
        for device_name, device_obj in self.testbed.devices.items():
            if device_name in self.visited_devices or device_name in self.lldp_configured or not device_obj.connected:
                continue
            device_to_configure.append(device_obj)
        if not device_to_configure:
            return
        pcall(self.configure_device_lldp_protocol,
              device= device_to_configure)
        
            
    def configure_device_lldp_protocol(self, device):
        '''If allowed to edit device configuration enable lldp on the device 
        if it is disabled and and then marks that configuration was done

        Args:
            device: the device having lldp enabled
        '''
        if not device.api.verify_lldp_in_state(max_time= self.timeout, check_interval=5):
            try:
                device.api.configure_lldp()
                self.lldp_configured.add(device.name)
            except Exception:
                log.error("Exception configuring cdp "
                            "for {device}".format(device = device.name),
                                                exc_info = True)
            

    def unconfigure_neighbor_discovery_protocols(self, device):
        '''Unconfigures neighbor discovery protocols on device if they
        were enabled by the script earlier

        Args:
            device: device to unconfigure protocols on
        '''

        # for each device in the list that had cdp configured by script,
        # disable cdp
        if device.name in self.cdp_configured:
            try:
                device.api.unconfigure_cdp()
            except Exception as e:
                log.error('Error unconfiguring cdp on device {}: {}'.format(device.name, e))

        # for each device in the list that had lldp configured by script,
        # disable lldp
        if device.name in self.lldp_configured:
            try:
                device.api.unconfigure_lldp()
            except Exception as e:
                log.error('Error unconfiguring lldp on device {}: {}'.format(device.name, e))

    def get_neighbor_info(self, device):
        '''Method designed to be used with pcall, gets the devices cdp and lldp
        neighbor data and then returns it in a dictionary format

        Args:
            device: target to device to call cdp and lldp commands on
        '''
        cdp = {}
        lldp = {}
        if device.os not in self.supported_os or not device.connected:
            return {device.name: {'cdp':cdp, 'lldp':lldp}}
        try:
            cdp = device.api.get_cdp_neighbors_info()
        except Exception:
            log.error("Exception occurred getting cdp info", exc_info = True)
        try:
            lldp = device.api.get_lldp_neighbors_info()
        except Exception:
            log.error("Exception occurred getting lldp info", exc_info = True)
        return {device.name: {'cdp':cdp, 'lldp':lldp}}

    def get_interfaces_ipV4_address(self, device):
        '''Get the ip address for all of the generated interfaces on the give device

        Args:
            device: device to get interface ip addresss for
        '''
        if not device.connected or device.os not in self.supported_os or len(device.interfaces) < 1:
            return
        for interface in device.interfaces.values():
            if interface.ipv4 is None:
                ip = device.api.get_interface_ipv4_address(interface.name)
                if ip:
                    ip = ipaddress.IPv4Interface(ip)
                    interface.ipv4 = ip

    def get_credentials_and_proxies(self, yaml):
        '''Takes a copy of the current credentials in the testbed for use in
        connecting to other devices

        Args:
            testbed: testbed to collect credentails and proxies for

        Returns:
            dict of credentials used in connections
            list of proxies used by testbed devices
        '''
        credential_dict = {}
        proxy_list = []
        for device in yaml['devices'].values():
            # get all connections used in the testbed
            for cred in device['credentials']:
                if cred not in credential_dict :
                    credential_dict[cred] = dict(device['credentials'][cred])
                elif device['credentials'][cred] not in credential_dict.values():
                    credential_dict[cred + str(len(credential_dict))] = dict(device['credentials'][cred])

            # get list of proxies used in connections
            for connect in device['connections'].values():
                if 'proxy' in connect:
                    if connect['proxy'] not in proxy_list:
                        proxy_list.append(connect['proxy'])
        return credential_dict, proxy_list
