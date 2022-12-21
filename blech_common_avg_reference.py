# Run through all the raw electrode data, 
# and subtract a common average reference from every electrode's recording
# The user specifies the electrodes to be used as a common average group 

# Import stuff!
import tables
import numpy as np
import os
import easygui
import sys
from tqdm import tqdm
import glob
import json

# Get name of directory with the data files
if sys.argv[1] != '':
    dir_name = os.path.abspath(sys.argv[1])
    if dir_name[-1] != '/':
        dir_name += '/'
else:
    dir_name = easygui.diropenbox('Please select data directory')

print(f'Processing : {dir_name}')

os.chdir(dir_name)


# Look for the hdf5 file in the directory
file_list = os.listdir('./')
hdf5_name = ''
for files in file_list:
        if files[-2:] == 'h5':
                hdf5_name = files

# Open the hdf5 file
hf5 = tables.open_file(hdf5_name, 'r+')

# Get the names of all files in this directory
file_list = os.listdir('./')

# Get the Intan amplifier ports used in the recordings
ports = list(set(f[4] for f in file_list if f[:3] == 'amp'))
# Sort the ports in alphabetical order
ports.sort()

# Count the number of electrodes on one of the ports 
# (assume all ports have equal number of electrodes)
num_electrodes = [int(f[-7:-4]) for f in file_list if f[:3] == 'amp']
num_electrodes = np.max(num_electrodes) + 1

# Read CAR groups from info file
# Every region is a separate group, multiple ports under single region is a separate group,
# emg is a separate group
dir_basename = os.path.basename(dir_name[:-1])
json_path = glob.glob(os.path.join(dir_name, dir_basename + '.info'))[0]
with open(json_path, 'r') as params_file:
    info_dict = json.load(params_file)

# Since electrodes are already in monotonic numbers (A : 0-31, B: 32-63)
# we can directly pull them
all_car_group_vals = []
all_car_group_names = []
for region_name, region_elecs in info_dict['electrode_layout'].items():
    for group in region_elecs:
        if len(group) > 0:
            all_car_group_vals.append(group)
            all_car_group_names.append(region_name)

# Select car groups which are not emg
all_car_group_vals, all_car_group_names = list(zip(*[
        [x,y] for x,y in zip(all_car_group_vals, all_car_group_names) \
                if 'emg' not in y
        ]))
num_groups = len(all_car_group_vals)

CAR_electrodes = all_car_group_vals
print(f" Number of groups : {len(CAR_electrodes)}")
for region,vals in zip(all_car_group_names, all_car_group_vals):
    print(f" {region} :: {vals}")

# Pull out the raw electrode nodes of the HDF5 file
raw_electrodes = hf5.list_nodes('/raw')
# Sort electrodes (just in case) so we can index them directly
sort_order = np.argsort([x.__str__() for x in raw_electrodes])
raw_electrodes = [raw_electrodes[i] for i in sort_order]
raw_electrodes_map = {
        int(str.split(electrode._v_pathname, 'electrode')[-1]):num \
                for num, electrode in enumerate(raw_electrodes)}

# First get the common average references by averaging across the electrodes picked for each group
print("Calculating common average reference for {:d} groups".format(num_groups))
common_average_reference = np.zeros((num_groups, raw_electrodes[0][:].shape[0]))
print('Calculating mean values')
for group in range(num_groups):
    print('Processing Group {}'.format(group))
    # Stack up the voltage data from all the electrodes that need 
    # to be averaged across in this CAR group   
    # In hindsight, don't stack up all the data, it is a huge memory waste. 
    # Instead first add up the voltage values from each electrode to the same array 
    # and divide by number of electrodes to get the average    
    for electrode_name in tqdm(CAR_electrodes[group]):
        electrode_ind = raw_electrodes_map[electrode_name]
        common_average_reference[group,:] += raw_electrodes[electrode_ind][:]
    # Average the voltage data across electrodes by dividing by the number 
    # of electrodes in this group
    common_average_reference[group, :] /= float(len(CAR_electrodes[group]))

print("Common average reference for {:d} groups calculated".format(num_groups))

# Now run through the raw electrode data and 
# subtract the common average reference from each of them
print('Performing background subtraction')
for electrode in tqdm(raw_electrodes):
        electrode_num = int(str.split(electrode._v_pathname, 'electrode')[-1])
        # Get the common average group number that this electrode belongs to
        # IMPORTANT!
        # We assume that each electrode belongs to only 1 common average reference group 
        group = int([i for i in range(num_groups) \
                if electrode_num in CAR_electrodes[i]][0])

        # Subtract the common average reference for that group from the 
        # voltage data of the electrode
        referenced_data = electrode[:] - common_average_reference[group]

        # First remove the node with this electrode's data
        hf5.remove_node(f"/raw/electrode{electrode_num:02}")

        # Now make a new array replacing the node removed above with the referenced data
        hf5.create_array("/raw", f"electrode{electrode_num:02}", referenced_data)
        hf5.flush()

        del referenced_data

hf5.close()
print("Modified electrode arrays written to HDF5 file after "\
        "subtracting the common average reference")
