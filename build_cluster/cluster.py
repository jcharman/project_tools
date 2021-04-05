#!/usr/bin/python

# Import required libraries
import requests
import subprocess
from os import system, remove
from time import sleep
import sys

# DO API settings.
apiToken = open('./token', 'r').read()          # Read in the API token from a file
apiRoot = "https://api.digitalocean.com/v2/"    # DigitalOcean API URL
sshKeys = [27339046]                            # SSH keys to be added to the VMs

# Inital node IPs 
nodeIP = []
lbIP = ""

# Save the nodes we know about.
def saveNodes():
    with open("nodes", "w+") as f:
        for ip in nodeIP:
            f.write(ip)
    with open("lb", "w+") as f:
        f.write(lbIP)

# Load in nodes from previous runs.
def loadNodes():
    global lbIP
    with open("nodes", "r") as f:
        for line in f:
            nodeIP.append(line)
    with open("lb", "r") as f:
        for line in f:
            lbIP = line


# Create a droplet using the DO API and return it's ID.
def createDroplet(name, region, size, image, keys):
    # The endpoint to use.218409560
    endpoint = "droplets"
    # Build the API reqest.
    requestURL = (apiRoot + endpoint)
    requestHeaders = {"Authorization": "Bearer " + apiToken}
    requestBody = {"name": name,"region": region,"size": size,"image": image,"backups": "false","ipv6": "false","user_data": "null","private_networking": "true","tags": [], "ssh_keys": keys}
    # Get the ID of the new droplet.
    dropletID = ((requests.post(requestURL, data=requestBody, headers=requestHeaders)).json()["droplet"]["id"])
    return dropletID

# Destroy a droplet and ALL of it's associated resources.
def destroyDroplet(dropletID):
    # The endpoint to use.
    endpoint = "droplets/" + dropletID + "/destroy_with_associated_resources"
    # Build the API reqest.
    requestURL = (apiRoot + endpoint + "/dangerous")
    requestHeaders = {"Authorization": "Bearer " + apiToken, "X-Dangerous": "true"}
    # Make the request and check the response code.
    responseCode = (requests.delete(requestURL, headers=requestHeaders)).status_code 
    if responseCode == 202:
        # Check the status of the delete if the API returns 202.
        requestURL = (apiRoot + endpoint + "/status")
        requestHeaders = {"Authorization": "Bearer " + apiToken}
        destroyJSON = (requests.get(requestURL, headers=requestHeaders)).json()
        
        # Wait for completed_at to have a value.
        while destroyJSON["completed_at"] == "":
            pass
        
        # Once it does, check if there were any failiures.
        if destroyJSON["failures"] == 0:
            return True
        else:
            return False
    else:
        return False

# Get the public IP of a droplet from it's ID.
def getDropletIP(dropletID):
    # The endpoint to use.
    endpoint = "droplets/" + str(dropletID)
    # Build the request.
    requestURL = (apiRoot + endpoint)
    requestHeaders = {"Authorization": "Bearer " + apiToken}
    # Try to get and return the IP, return False on IndexError.
    try:
        dropletIP = (requests.get(requestURL, headers=requestHeaders).json()["droplet"]["networks"]["v4"][1]["ip_address"])
    except IndexError:
        return False
    
    return dropletIP

# Get the private IP of a droplet from it's ID.
def getDropletPrivateIP(dropletID):
    # The endpoint to use.
    endpoint = "droplets/" + str(dropletID)
    # Build the request.
    requestURL = (apiRoot + endpoint)
    requestHeaders = {"Authorization": "Bearer " + apiToken}
    # Try to get and return the IP, return False on IndexError.
    try:
        dropletIP = (requests.get(requestURL, headers=requestHeaders).json()["droplet"]["networks"]["v4"][0]["ip_address"])
    except IndexError:
        return False
    
    return dropletIP

# Get the average load across the cluster.
def getLoad(nodes):
    loadValues = []
    # Get the 1m load average for each node.
    for node in nodes:
        load = float(subprocess.check_output("ssh root@" + node + " cat /proc/loadavg | awk {'print $1'}", shell=True).decode().strip("\n"))
        loadValues.append(load)
    # Calculate the average load across the cluster.
    avgLoad = 0
    for value in loadValues:
        avgLoad = avgLoad + value
    avgLoad = avgLoad / len(loadValues)
    return avgLoad

# Set up a new node to make it ready to join the cluster.
def setupNode(node, privateIP):
    # Add this node to the list of nodes.
    nodeIP.append(privateIP)

    # Construct a cluster address from the nodes we know about
    clusterAddress = "gcomm://" + ','.join(nodeIP)

    # Construct a my.cnf for the new node.
    with open("./my.cnf.tmpl") as f:
        with open("my.cnf", "w+") as f1:
            for line in f:
                f1.write(line)
            f1.write("wsrep_cluster_address=" + clusterAddress + "\n")
            f1.write("wsrep_node_address=" + privateIP)

    # Create a new hosts file for Ansible
    hostsFile = open("./hosts.tmp","w+")
    hostsFile.write(str(node))
    hostsFile.close()
    
    # Run the new_node.yml Ansible playbook on the node.
    returnVal = system("ansible-playbook ./new_node.yaml -i ./hosts.tmp")
    returnVal = int(bin(returnVal).replace("0b", "").rjust(16, '0')[:8], 2)
    if returnVal != 0:
        raise RuntimeError(f'The system command exited with return code {returnVal}')

    # Delete the temporary file and the my.cnf we created
    remove("./hosts.tmp")
    remove("./my.cnf")

# Add the node in to HAProxy.
# This function assumes that the node is ready for public traffic already!
def updateLB(lb):
    # Create a HAProxy config for the current cluster.
    with open("./haproxy.cfg.tmpl") as f:
        with open("haproxy.cfg", "w+") as f1:
            for line in f:
                f1.write(line)
            for ip in nodeIP:
                f1.write("    server  " + "cluster-node-" + str(nodeIP.index(ip)) + " " + ip + ":80 check\n")

    # Create a hosts file for Ansible to use
    hostsFile = open("hosts.tmp", "w+")
    hostsFile.write(lb)
    hostsFile.close()

    returnVal = system("ansible-playbook ./haproxy.yaml -i ./hosts.tmp")
    returnVal = int(bin(returnVal).replace("0b", "").rjust(16, '0')[:8], 2)
    if returnVal != 0:
        raise RuntimeError(f'The system command exited with return code {returnVal}')
    
    remove("./hosts.tmp")

# Wait for a machine to be accepting SSH connections.
def waitForSSH(ip):
    print("Waiting for SSH to be available on " + ip)
    success = 1
    while success != 0:
        success = system("ssh -o StrictHostKeyChecking=no " + str(ip) + " echo SSH is working!")


# Create a DO droplet and perform basic setup on it.
def startFirstNode():
    print("Starting up the first node in a new cluster...")

    print("Creating a new DigitalOcean droplet...")
    nodeID = createDroplet("node-0", "lon1", "s-1vcpu-1gb", "centos-8-x64", sshKeys)
    
    print("Wating for the node to be assigned an IP address...")
    while getDropletIP(nodeID) == False:
        pass

    ipAddr = getDropletIP(nodeID)
    print(ipAddr)
    privateIP = getDropletPrivateIP(nodeID)
    print(privateIP)

    # Give the node some time to come up.
    waitForSSH(ipAddr)
    
    # Construct a cluster address from the nodes we know about
    clusterAddress = "gcomm://" + ','.join(nodeIP)

    # Construct a my.cnf for the new node.
    with open("./my.cnf.tmpl") as f:
        with open("my.cnf", "w+") as f1:
            for line in f:
                f1.write(line)
            f1.write("wsrep_cluster_address=" + clusterAddress + "\n")
            f1.write("wsrep_node_address=" + privateIP)

    hostsFile = open("hosts.tmp", "w+")
    hostsFile.write(ipAddr)
    hostsFile.close()
    print("Running the Ansible playbook...")
    returnVal = system("ansible-playbook ./first_node.yaml -i ./hosts.tmp")
    returnVal = int(bin(returnVal).replace("0b", "").rjust(16, '0')[:8], 2)
    if returnVal != 0:
        raise RuntimeError(f'The system command exited with return code {returnVal}')
    
    remove("./hosts.tmp")

    nodeIP.append(privateIP)
    
# Start up a HAProxy load balancer in DO 
def startLoadBalancer():
    global lbIP
    print("Creating a new DigitalOcean droplet...")
    nodeID = createDroplet("lb", "lon1", "s-1vcpu-1gb", "centos-8-x64", sshKeys)

    print("Wating for the node to be assigned an IP address...")
    while getDropletIP(nodeID) == False:
        pass
    
    ipAddr = getDropletIP(nodeID)
    print(ipAddr)
    lbIP = ipAddr

    # Give the node some time to come up.
    waitForSSH(ipAddr)

    print("Running updateLB()...")
    updateLB(ipAddr)

# Add a new droplet to the cluster
def scaleUp():
    print("Creating a new DigitalOcean droplet...")
    nodeID = createDroplet("node-" + str(len(nodeIP)), "lon1", "s-1vcpu-1gb", "centos-8-x64", sshKeys)

    print("Wating for the node to be assigned an IP address...")
    while getDropletIP(nodeID) == False:
        pass
    
    ipAddr = getDropletIP(nodeID)
    print(ipAddr)
    privateIP = getDropletPrivateIP(nodeID)
    print(privateIP)
    
    waitForSSH(ipAddr)

    setupNode(ipAddr, privateIP)
    updateLB(lbIP)

try:
    if sys.argv[1] == "new":
        try:
            remove("nodes")
            remove("lb")
        except:
            pass
        numNodes = int(sys.argv[2])
        startFirstNode()
        startLoadBalancer()
        startedNodes = 1
        while startedNodes < numNodes:
            scaleUp()
            startedNodes += 1
        saveNodes()
    elif sys.argv[1] == "scaleup":
        loadNodes()
        scaleUp()
        saveNodes()


except Exception as e:
    print(e)
    exit()