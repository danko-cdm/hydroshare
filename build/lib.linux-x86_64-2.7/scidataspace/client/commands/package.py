from scidataspace.client.commands.util import UNDEFINED,is_geounit_selected, run_command
from scidataspace.client.commands._leveldb2json import create_graph
#from scidataspace.client.commands.transfer import globus_transfer

import docker
import json
import os, sys
import re
import shutil

import hashlib
from datetime import datetime

def create_hash(input_string):
    h = hashlib.new('ripemd160')
    #input_string = "geounitname.geounitid.programname <with special chars stripped off>"
    str_now=str(datetime.now())
    h.update(input_string.encode('utf-8')+str_now)
    return h.hexdigest()

def build(cde_package_root, tag=None, cmd=None):
    # create Dockerfile
    with open(cde_package_root + '/Dockerfile', 'w') as f:
        f.write('''FROM ubuntu
COPY cde-package/ /home/cde-package
''')
        # for key in os.environ:
        #     value = os.environ[key]
        #     if value is not None and value.strip() != '':
        #         f.write('ENV {key} {value}\n'.format(key=key, value=value))
        #     else:
        #         pass
        #         # will ignore this variable but will not raise error
        #         # print "wrong k={key} value={value}".format(key=key, value=value)
        if cmd:
            f.write('CMD {0}\n'.format(cmd))

    # build image
    c = docker.Client(base_url='unix://var/run/docker.sock', version="1.12")
    docker_image_id=None
    for response in c.build(path=cde_package_root, tag=tag, rm=True):
        #print response,
        s = json.loads(response)
        if 'stream' in s:
            #print s['stream'],
            match = re.search('Successfully built (.*)', s['stream'])
            if match:
                docker_image_id = match.group(1)
        elif 'errorDetail' in s:
            # raise Exception(s['errorDetail']['message'])
            print "Exception:",s['errorDetail']['message']

    if docker_image_id:
        print "Successfully built image id ",docker_image_id
    else:
        print "Could not create image"
    return docker_image_id

#######################################
#   Parse package
#######################################
def parse_cmd_package(cmd_splitted, catalog_id, geounit_id, datasetClient, db, cfg):
    if  not is_geounit_selected(geounit_id): return

    working_path = os.getcwd()
    home_folder = os.path.expanduser("~")
    package_file_path = os.path.dirname(os.path.abspath(__file__))
    #print "current_path=", current_path
    executable = os.path.join(package_file_path, "bin","ptu")
    # executable = "/home/ubuntu/cristian/CDE/cde" # this was added for Bakinam machine
    packages_json_file = os.path.join(home_folder, ".gdclient","packages","packages.json")
    packages_directory = os.path.join(home_folder, ".gdclient","packages")
    if not os.path.exists(packages_directory):
        os.makedirs(packages_directory)
    # print "packages_json_file=",packages_json_file
    try:
        with open(packages_json_file) as data_file:
            packages_json = json.load(data_file)
    except:
        packages_json = {}
        with open(packages_json_file, 'w') as outfile:
            json.dump(packages_json, outfile, sort_keys = True, indent = 4)
    boolWithProvenance = False

    cmd_2 = cmd_splitted.get(1,"")
    ########
    #       list subcommand
    ########
    if cmd_2 == "list":
        print len(packages_json)," packages available:"
        for k in packages_json:
            print k,"  ",\
            packages_json[k]['date'],'   ',\
            packages_json[k]['command']
        return

    ########
    #       delete subcommand
    ########
    if cmd_2 == "delete":
        package_id = cmd_splitted.get(2,"")
        if packages_json.get(package_id,UNDEFINED) == UNDEFINED:
            print "cannot find package id ",package_id
            return
        packages_json.pop(package_id, None)
        package_directory = os.path.join(home_folder, ".gdclient","packages",package_id)
        try:
            shutil.rmtree(package_directory)
        except Exception as e:
            print "cannot delete folder"
            sys.stderr.write(str(e) + "\n")

        with open(packages_json_file, 'w') as outfile:
            json.dump(packages_json, outfile, sort_keys = True, indent = 4)
        return


    ########
    #       add subcommand
    ########
    if cmd_2 == "add":
        package_id = cmd_splitted.get(2,"")
        if packages_json.get(package_id,UNDEFINED) == UNDEFINED:
            print "cannot find package id ",package_id
            return

        # TODO add member and transfer through globus
        # transfer through globus
        globus_package_name = globus_transfer(package_id, cfg)

        # add member with newly created package

        try:
            r, members = datasetClient.create_member(catalog_id,geounit_id,dict(data_type="file", data_uri=globus_package_name))
            # print members['id']
            print "Added member: ", globus_package_name
            db.Put("member."+globus_package_name, str(members['id']))
        except:
            print "Cannot add member: "+globus_package_name
            pass
        return


    ########
    #       test subcommand
    ########
    if cmd_2 == "test":
        package_id = cmd_splitted.get(2,"")
        if packages_json.get(package_id,UNDEFINED) == UNDEFINED:
            print "cannot find package id ",package_id
            return
        docker_workdir="/home/cde-package/cde-root%s"%packages_json[package_id]['workdir']
        docker_command="/home/cde-package/cde-exec %s"%packages_json[package_id]['command']
        cmd_to_run = "docker run --privileged -w %s %s %s" %(docker_workdir,
                                                package_id,
                                                docker_command)
        # print "cmd_to_run=", cmd_to_run

        # this will create cde.option file and cde-package directory
        print( cmd_to_run)

        try:
            run_command(cmd_to_run)
        except Exception as e:
            sys.stderr.write(str(e) + "\n")

        return

    cmd_level_index = 2
    # with provenance - create json
    if cmd_2 == "provenance":
        boolWithProvenance = True
        cmd_level_index += 1

    ########
    #       individual subcommand
    ########

    cmd_level = cmd_splitted.get(cmd_level_index,"")
    if cmd_level == 'individual':
        try:
            cde_directory = os.path.join(working_path, "cde-package")

            # make sure that LevelDB database does not exist
            if os.path.isdir(cde_directory):
                shutil.rmtree(cde_directory)

            user_command = ' '.join(cmd_splitted[cmd_level_index+1:])
            cmd_to_run = "%s %s 2>/dev/null" %(executable, user_command)
            # print "cmd_to_run=", cmd_to_run

            # this will create cde.option file and cde-package directory
            run_command(cmd_to_run)
            package_hash = create_hash(cmd_to_run)
            package_directory = os.path.join(home_folder, ".gdclient","packages",package_hash)
            if not os.path.exists(package_directory):
                os.makedirs(package_directory)

            shutil.move(os.path.join(working_path, "cde.options"), package_directory)
            shutil.move(cde_directory, package_directory)

            # create json file, if is specified in command
            if boolWithProvenance:
                provenance_package_directory = os.path.join(package_directory,"cde-package", "provenance.cde-root.1.log")
                # print "pkg dir=",provenance_package_directory
                graph_dict = create_graph(provenance_package_directory)

                json_file_name = os.path.join(package_directory,"filex.json")

                with open(json_file_name, 'w') as outfile:
                    json.dump(graph_dict, outfile, sort_keys = True, indent = 4)

            # need to store package hash in a list
            print "package_hash=",package_hash
            packages_json[package_hash]= dict(command= user_command,
                                              date=str(datetime.now()),
                                              workdir=working_path)
            with open(packages_json_file, 'w') as outfile:
                json.dump(packages_json, outfile, sort_keys = True, indent = 4)
        except:
            print "Unexpected error:", sys.exc_info()
            print "USAGE: --package level individual <program to execute>"
            pass
    ########
    #       collaboration subcommand
    ########

    elif cmd_level == 'collaboration':
        package_id = cmd_splitted.get(cmd_level_index+1,"")
        # test if individual is completed ; package exists
        package_directory = os.path.join(home_folder, ".gdclient","packages",package_id)
        if packages_json.get(package_id,UNDEFINED) == UNDEFINED:
            print "cannot find package id ",package_id
            return
        package_directory = os.path.join(home_folder, ".gdclient","packages",package_id)
        if not os.path.isdir(package_directory):
            print "ERROR: Package folder does not exists"
            return

        #  create a docker container
        docker_container_id = UNDEFINED
        try:
            # build('../cde-package', tag='scidataspace/test:v2', cmd='/root/d/hello.py')
            docker_container_id = build(package_directory, tag=package_id)
            if docker_container_id is not None:
                print "Successfull"
                return docker_container_id
            else:
                raise Exception("Could not create container")
        except Exception, ex:
            print "Error: {0}".format(ex)

    ########
    #       community subcommand
    ########

    elif cmd_level == 'community':
        # TODO: test if collaboration is completed ; docker file is created

        # TODO: put a docker file as part of docker container
        pass
    else:
        print "USAGE: package [provenance] list| add | delete| level [individual <program name>| collaboration <package id>| community] "



