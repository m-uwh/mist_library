'''
-------------------------------------------------------------------------------

    Written by Thomas Munzer (tmunzer@juniper.net)
    Github repository: https://github.com/tmunzer/Mist_library/

    This script is licensed under the MIT License.

-------------------------------------------------------------------------------
Python script to backup all the devices from an organization. It will backup the
devices claim codes (if any), configuration (including position on the maps) and 
pictures.
You can use the script "org_inventory_deploy.py" to restore the generated backup 
files to an existing organization or to a new one.

This script will not change/create/delete/touch any existing objects. It will 
just retrieve every single object from the organization.

-------
Requirements:
mistapi: https://pypi.org/project/mistapi/

-------
Usage:
This script can be run as is (without parameters), or with the options below.
If no options are defined, or if options are missing, the missing options will
be asked by the script or the default values will be used.

It is recomended to use an environment file to store the required information
to request the Mist Cloud (see https://pypi.org/project/mistapi/ for more 
information about the available parameters).

-------
Script Parameters:
-h, --help              display this help
-o, --org_id=           Set the org_id
-b, --backup_folder=    Path to the folder where to save the org backup (a 
                        subfolder will be created with the org name)
                        default is "./org_backup"
-l, --log_file=         define the filepath/filename where to write the logs
                        default is "./script.log"
-e, --env=              define the env file to use (see mistapi env file 
                        documentation here: https://pypi.org/project/mistapi/)
                        default is "~/.mist_env"

-------
Examples:
python3 ./org_inventory_backup.py     
python3 ./org_inventory_backup.py --org_id=203d3d02-xxxx-xxxx-xxxx-76896a3330f4 

'''

#### IMPORTS ####
import logging
import sys
import os
import json
import getopt
import urllib.request

try:
    import mistapi
    from mistapi.__logger import console
except:
    print("""
Critical: 
\"mistapi\" package is missing. Please use the pip command to install it.

# Linux/macOS
python3 -m pip install mistapi

# Windows
py -m pip install mistapi
    """)
    sys.exit(2)
try:
    if (int(mistapi.__version__.split(".")[1]) < 36):
        raise Exception
except:
    print("""
Critical: 
Your version of \"mistapi\" package is too old to run this script. 
Please use the pip command to upgrade it.

# Linux/macOS
python3 -m pip install --upgrade mistapi

# Windows
py -m pip install --upgrade mistapi
    """)
    sys.exit(2)

#####################################################################
#### PARAMETERS #####
backup_folder = "./org_backup"
backup_file = "./org_inventory_file.json"
file_prefix = ".".join(backup_file.split(".")[:-1])
log_file = "./script.log"
env_file = "~/.mist_env"

#####################################################################
#### LOGS ####
logger = logging.getLogger(__name__)

#####################################################################
# BACKUP OBJECTS REFS
device_types = ["ap","switch","gateway","mxedge"]

#####################################################################
# PROGRESS BAR AND DISPLAY
class ProgressBar():
    def __init__(self):        
        self.steps_total = 0
        self.steps_count = 0

    def _pb_update(self, size:int=80):   
        if self.steps_count > self.steps_total: 
            self.steps_count = self.steps_total

        percent = self.steps_count/self.steps_total
        delta = 17
        x = int((size-delta)*percent)
        print(f"Progress: ", end="")
        print(f"[{'█'*x}{'.'*(size-delta-x)}]", end="")
        print(f"{int(percent*100)}%".rjust(5), end="")

    def _pb_new_step(self, message:str, result:str, inc:bool=False, size:int=80, display_pbar:bool=True):
        if inc: self.steps_count += 1
        text = f"\033[A\033[F{message}"
        print(f"{text} ".ljust(size + 4, "."), result)
        print("".ljust(80))
        if display_pbar: self._pb_update(size)

    def _pb_title(self, text:str, size:int=80, end:bool=False, display_pbar:bool=True):
        print("\033[A")
        print(f" {text} ".center(size, "-"),"\n")
        if not end and display_pbar: 
            print("".ljust(80))
            self._pb_update(size)

    def set_steps_total(self, steps_total:int):
        self.steps_total = steps_total

    def log_message(self, message, display_pbar:bool=True):
        self._pb_new_step(message, " ", display_pbar=display_pbar)

    def log_success(self, message, inc:bool=False, display_pbar:bool=True):
        logger.info(f"{message}: Success")
        self._pb_new_step(message, "\033[92m\u2714\033[0m\n", inc=inc, display_pbar=display_pbar)

    def log_failure(self, message, inc:bool=False, display_pbar:bool=True):
        logger.error(f"{message}: Failure")
        self._pb_new_step(message, '\033[31m\u2716\033[0m\n', inc=inc, display_pbar=display_pbar)

    def log_title(self, message, end:bool=False, display_pbar:bool=True):
        logger.info(message)
        self._pb_title(message, end=end, display_pbar=display_pbar)

pb = ProgressBar()

#####################################################################
#### SITE FUNCTIONS ####
def _save_site_info(site:dict, backup:dict):
    backup["org"]["sites"][site["name"]] = {
        "id": site["id"],  "old_maps_ids": {}, "devices": []}
    backup["org"]["old_sites_id"][site["name"]] = site["id"]


def _backup_site_id_dict(site:dict, backup:dict):
    if site["name"] in backup["org"]["sites"]:
        console.warning(f"Two sites are using the same name {site['name']}!")
        console.warning("This will cause issue during the backup and the restore process.")
        console.warning("I recommand you to rename one of the two sites.")
        loop = True
        while loop:
            resp = input("Do you want to continue anyway (y/N)? ")
            if resp.lower() == "y":
                loop = False
                _save_site_info(site, backup)
            elif resp.lower() == "n" or resp == "":
                loop = False
                sys.exit(200)
    else:
        _save_site_info(site, backup)

def _backup_site_maps(mist_session:mistapi.APISession, site):
    response = mistapi.api.v1.sites.maps.listSiteMaps(mist_session, site["id"])
    backup_maps = mistapi.get_all(mist_session, response)
    maps_ids = {}
    for xmap in backup_maps:
        if xmap["name"] in maps_ids:
            console.warning(
                f"Two maps are using the same name {xmap['name']} in the same site {site['name']}!")
            console.warning("This will cause issue during the backup and the restore process.")
            console.warning("It is recommanded you to rename one of the two maps.")
            loop = True
            while loop:
                resp = input("Do you want to continue anyway (y/N)? ")
                if resp.lower() == "y":
                    loop = False
                    ["maps"].append({xmap["name"]: xmap["id"]})
                    ["maps_ids"][xmap["name"]] = xmap["id"]
                elif resp.lower() == "n" or resp == "":
                    loop = False
                    sys.exit(200)
        else:
            maps_ids[xmap["name"]] = xmap["id"]
    return maps_ids

def _no_magic(backup:dict, site_name:str, device:dict, device_type:str=None):
    if not device["mac"] in backup["org"]["magics"]:
        backup["org"]["devices_without_magic"].append({
                "site": site_name, 
                "device_type": device.get("type", device_type), 
                "model": device.get("model"), 
                "name": device.get("name"), 
                "mac": device.get("mac"),
                "serial":device.get("serial")
                })

#####################################################################
#### INVENTORY FUNCTIONS ####
def _backup_inventory(mist_session:mistapi.APISession, org_id:str, org_name:str=None, backup:dict={}):
    pb.log_title(f"Backuping Org {org_name} Elements ")

    backup["org"]["id"] = org_id
    ################################################
    ##  Backuping inventory
    for device_type in device_types:
        message=f"Backuping {device_type} magics"
        pb.log_message(message)
        try:
            response = mistapi.api.v1.orgs.inventory.getOrgInventory(mist_session, org_id, type=device_type, limit=1000)
            inventory = mistapi.get_all(mist_session, response)
            for data in inventory:
                if data.get("magic"):
                    backup["org"]["magics"][data["mac"]] =  data["magic"]
            pb.log_success(message, True)
        except Exception as e:
            pb.log_failure(message, True)
            logger.error("Exception occurred", exc_info=True)

    ################################################
    ##  Retrieving org MxEdges

    message=f"Backuping Org MxEdges"
    pb.log_message(message)
    try:
        response = mistapi.api.v1.orgs.mxedges.listOrgMxEdges(mist_session, org_id, limit=1000)
        mxedges = mistapi.get_all(mist_session, response)
        backup["org"]["mxedges"] = mxedges
        pb.log_success(message, True)
    except Exception as e:
        pb.log_failure(message, True)
        logger.error("Exception occurred", exc_info=True)
    for mxedge in mxedges:
        _no_magic(backup, "Org", mxedge, "mxedge")        
        
    ################################################
    ##  Retrieving device profiles
    message=f"Backuping Device Profiles"
    pb.log_message(message)
    try:
        response = mistapi.api.v1.orgs.deviceprofiles.listOrgDeviceProfiles(mist_session, org_id, limit=1000)
        deviceprofiles = mistapi.get_all(mist_session, response)
        for deviceprofile in deviceprofiles:
            backup["org"]["old_deviceprofiles_id"][deviceprofile["name"]] = deviceprofile["id"]
        pb.log_success(message, True)
    except Exception as e:
        pb.log_failure(message, True)
        logger.error("Exception occurred", exc_info=True)
    ################################################
    ##  Retrieving evpntopologies
    message=f"Backuping EVPN Topologies"
    pb.log_message(message)
    try:
        response = mistapi.api.v1.orgs.evpn_topologies.listOrgEvpnTopologies(mist_session, org_id)
        evpn_topologies = mistapi.get_all(mist_session, response)
        for evpn_topology in evpn_topologies:
            backup["org"]["old_evpntopo_id"][deviceprofile["name"]] = evpn_topology["id"]
        pb.log_success(message, True)
    except Exception as e:
        pb.log_failure(message, True)
        logger.error("Exception occurred", exc_info=True)

    ################################################
    ##  Retrieving Sites list
    message=f"Retrieving Sites list"
    pb.log_message(message)
    try:
        response = mistapi.api.v1.orgs.sites.listOrgSites(mist_session, org_id, limit=1000)
        sites = mistapi.get_all(mist_session, response)
        pb.log_success(message, True)
    except Exception as e:
        pb.log_failure(message, True)
        logger.error("Exception occurred", exc_info=True)

    ################################################
    ## Backuping Sites Devices
    for site in sites:
        pb.log_title(f"Backuping Site {site['name']}")
        message=f"Devices List"
        pb.log_message(message)
        try:
            _backup_site_id_dict(site, backup)
            backup["org"]["sites"][site["name"]]["old_maps_ids"] = _backup_site_maps(mist_session, site)
            response = mistapi.api.v1.sites.devices.listSiteDevices(mist_session, site["id"], type="all", limit=1000)
            devices = mistapi.get_all(mist_session, response)
            backup["org"]["sites"][site["name"]]["devices"] = devices
            pb.log_success(message, True)
        except Exception as e:
            pb.log_failure(message, True)
            logger.error("Exception occurred", exc_info=True)
        ################################################
        ## Backuping Site Devices Images
        for device in devices:
            _no_magic(backup, site["name"], device)
            message=f"Backuping {device['type'].upper()} {device['serial']} images"
            pb.log_message(message)
            try:
                i = 1
                while f"image{i}_url" in device:
                    url = device[f"image{i}_url"]
                    image_name = f"{file_prefix}_org_{org_id}_device_{device['serial']}_image_{i}.png"
                    urllib.request.urlretrieve(url, image_name)
                    i += 1
                pb.log_success(message, True)
            except Exception as e:
                pb.log_failure(message, True)
                logger.error("Exception occurred", exc_info=True)
    
    ################################################
    ## End
    pb.log_title(f"Backup Done", end=True)
    print()

def _save_to_file(backup_file, org_name:str, backup):
    backup_path = f"./org_backup/{org_name}/{backup_file.replace('./','')}"
    message=f"Saving to file {backup_path} "
    pb.log_message(message, display_pbar=False)
    try:
        with open(backup_file, "w") as f:
            json.dump(backup, f)
        pb.log_success(message, display_pbar=False)
    except Exception as e:
        pb.log_failure(message, display_pbar=False)
        logger.error("Exception occurred", exc_info=True)


def _start_inventory_backup(mist_session:mistapi.APISession, org_id:str, org_name:str):
    # FOLDER
    try:
        if not os.path.exists(backup_folder):
            os.makedirs(backup_folder)
        os.chdir(backup_folder)
        if not os.path.exists(org_name):
            os.makedirs(org_name)
        os.chdir(org_name)
    except Exception as e:
        print(e)
        logger.error("Exception occurred", exc_info=True)
    # PREPARE PROGRESS BAR
    try:
        device_count = 0
        for device_type in device_types:
            response = mistapi.api.v1.orgs.inventory.getOrgInventory(mist_session, org_id, type=device_type, limit=1)
            if (response.headers.get("X-Page-Total")): device_count += int(response.headers.get("X-Page-Total"))
            else: device_count += len(response.data)
        response = mistapi.api.v1.orgs.sites.countOrgSites(mist_session, org_id, limit=1)
        if (response.headers.get("X-Page-Total")): site_count = int(response.headers.get("X-Page-Total"))
        else: site_count = len(response.data)
        pb.set_steps_total(2 + len(device_types) + site_count + device_count)
    except Exception as e:
        logger.error("Exception occurred", exc_info=True)
        sys.exit(0)

    backup = {
        "org": {"id": "", "sites": {}, "old_sites_id": {}, "old_deviceprofiles_id": {}, "old_evpntopo_id": {}, "magics": {}, "devices_without_magic":[] }
    }
    _backup_inventory(mist_session, org_id, org_name, backup)    
    _save_to_file(backup_file, org_name, backup)
    if backup["org"]["devices_without_magic"]:
        console.warning("It was not possible to retrieve the claim codes for the following devices:")
        mistapi.cli.display_list_of_json_as_table(backup["org"]["devices_without_magic"], ["site", "device_type", "model", "name", "mac", "serial"])
        print()


def start(mist_session:mistapi.APISession, org_id:str, backup_folder_param:str=None):
    '''
    Start the backup process

    PARAMS
    -------
    :param  mistapi.APISession  dst_apisession      - mistapi session with `Super User` access the destination Org, already logged in
    :param  str                 org_id              - org_id of the org to backup
    :param  str                 org_name            - Org name where to deploy the inventory. This parameter requires "org_id" to be defined
    :param  str                 backup_folder_param - Path to the folder where to save the org backup (a subfolder will be created with the org name). default is "./org_backup"
    
    '''
    current_folder = os.getcwd()
    if backup_folder_param:
        global backup_folder 
        backup_folder = backup_folder_param
    if not org_id:
        org_id = mistapi.cli.select_org(mist_session)[0]
    org_name = mistapi.api.v1.orgs.orgs.getOrgInfo(mist_session, org_id).data["name"]
    _start_inventory_backup(mist_session, org_id, org_name)
    os.chdir(current_folder)

#####################################################################
#### USAGE ####
def usage():
    print('''
-------------------------------------------------------------------------------

    Written by Thomas Munzer (tmunzer@juniper.net)
    Github repository: https://github.com/tmunzer/Mist_library/

    This script is licensed under the MIT License.

-------------------------------------------------------------------------------
Python script to backup all the devices from an organization. It will backup the
devices claim codes (if any), configuration (including position on the maps) and 
pictures.
You can use the script "org_inventory_deploy.py" to restore the generated backup 
files to an existing organization or to a new one.

This script will not change/create/delete/touch any existing objects. It will 
just retrieve every single object from the organization.

-------
Requirements:
mistapi: https://pypi.org/project/mistapi/

-------
Usage:
This script can be run as is (without parameters), or with the options below.
If no options are defined, or if options are missing, the missing options will
be asked by the script or the default values will be used.

It is recomended to use an environment file to store the required information
to request the Mist Cloud (see https://pypi.org/project/mistapi/ for more 
information about the available parameters).

-------
Script Parameters:
-h, --help              display this help
-o, --org_id=           Set the org_id
-b, --backup_folder=    Path to the folder where to save the org backup (a 
                        subfolder will be created with the org name)
                        default is "./org_backup"
-l, --log_file=         define the filepath/filename where to write the logs
                        default is "./script.log"
-e, --env=              define the env file to use (see mistapi env file 
                        documentation here: https://pypi.org/project/mistapi/)
                        default is "~/.mist_env"

-------
Examples:
python3 ./org_inventory_backup.py     
python3 ./org_inventory_backup.py --org_id=203d3d02-xxxx-xxxx-xxxx-76896a3330f4 

''')

#####################################################################
#### SCRIPT ENTRYPOINT ####
if __name__ == "__main__":
    try:
        opts, args = getopt.getopt(sys.argv[1:], "ho:e:l:b:", [
                                   "help", "org_id=", "env=", "log_file=", "backup_folder="])
    except getopt.GetoptError as err:
        console.error(err)
        usage()

    org_id = None
    backup_folder_param = None
    for o, a in opts:
        if o in ["-h", "--help"]:
            usage()
        elif o in ["-o", "--org_id"]:
            org_id = a      
        elif o in ["-e", "--env"]:
            env_file = a
        elif o in ["-l", "--log_file"]:
            log_file = a
        elif o in ["-b", "--backup_folder"]:
            backup_folder_param = a
        else:
            assert False, "unhandled option"
    
    #### LOGS ####
    logging.basicConfig(filename=log_file, filemode='w')
    logger.setLevel(logging.DEBUG)
    ### START ###
    apisession = mistapi.APISession(env_file=env_file)
    apisession.login()
    start(apisession, org_id, backup_folder_param)
