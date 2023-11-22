import os
import tables
import numpy as np
import easygui
import ast
import re
import pylab as plt
import matplotlib.image as mpimg
from sklearn.mixture import GaussianMixture
import argparse
import pandas as pd

# Import 3rd party code
from utils import blech_waveforms_datashader
from utils.blech_utils import entry_checker, imp_metadata
import utils.blech_post_process_utils as post_utils

from importlib import reload
reload(post_utils)
this_descriptor_handler = post_utils.unit_descriptor_handler(hf5, data_dir)
self = this_descriptor_handler

# Set seed to allow inter-run reliability
# Also allows reusing the same sorting sheets across runs
np.random.seed(0)

# Get directory where the hdf5 file sits, and change to that directory
# Get name of directory with the data files
# Create argument parser
parser = argparse.ArgumentParser(
        description = 'Spike extraction and sorting script')
parser.add_argument('--dir-name',  '-d', help = 'Directory containing data files')
parser.add_argument('--show-plot', '-p', 
        help = 'Show waveforms while iterating (True/False)', default = 'True')
parser.add_argument('--sort-file', '-f', help = 'CSV with sorted units',
                    default = None)
args = parser.parse_args()

if args.sort_file is not None:
    if not (args.sort_file[-3:] == 'csv'):
        raise Exception("Please provide CSV file")
    sort_table = pd.read_csv(args.sort_file)
    sort_table.fillna('',inplace=True)
    # Check when more than one cluster is specified
    sort_table['len_cluster'] = \
            [len(re.findall('[0-9]+',str(x))) for x in sort_table.Cluster]
    
    # Get splits and merges out of the way first
    sort_table.sort_values(['len_cluster','Split'],ascending=False, inplace=True)
    true_index = sort_table.index
    sort_table.reset_index(inplace=True)

data_dir = '/home/abuzarmahmood/Desktop/blech_clust/pipeline_testing/test_data_handling/test_data/KM45_5tastes_210620_113227_new'
metadata_handler = imp_metadata([[],data_dir])

#if args.dir_name is not None: 
#    metadata_handler = imp_metadata([[],args.dir_name])
#else:
#    metadata_handler = imp_metadata([])

dir_name = metadata_handler.dir_name
os.chdir(dir_name)
file_list = metadata_handler.file_list
hdf5_name = metadata_handler.hdf5_name
# Open the hdf5 file
hf5 = tables.open_file(hdf5_name, 'r+')

# Instantiate unit_descriptor_handler
this_descriptor_handler = post_utils.unit_descriptor_handler(hf5, dir_name)

# Clean up the memory monitor files, pass if clean up has been done already
post_utils.clean_memory_monitor_data()  

# Delete the raw node, if it exists in the hdf5 file, to cut down on file size
post_utils.delete_raw_recordings(hf5)


# Make the sorted_units group in the hdf5 file if it doesn't already exist
if not '/sorted_units' in hf5:
    hf5.create_group('/', 'sorted_units')

# Run an infinite loop as long as the user wants to 
# pick clusters from the electrodes   

while True:

    ############################################################
    # Get unit details and load data
    ############################################################

    # If sort_file given, iterate through that, otherwise ask user
    continue_bool, electrode_num, num_clusters, clusters = \
            post_utils.get_electrode_details(
                    args, 
                    this_descriptor_handler.counter)

    # For all other continue_bools, if false, end iteration
    # That will return them to this one
    # At that point, if continue_bool is False, exit
    if not continue_bool: exit()

    # Print out selections
    print('||| Electrode {}, Solution {}, Cluster {} |||'.\
            format(electrode_num, num_clusters, clusters))


    # Load data from the chosen electrode and solution
    (
        spike_waveforms,
        spike_times,
        pca_slices,
        energy,
        amplitudes,
        predictions,
    ) = post_utils.load_data_from_disk(electrode_num, num_clusters)

    # Re-show images of neurons so dumb people like Abu can make sure they
    # picked the right ones
    #if ast.literal_eval(args.show_plot):
    if args.show_plot == 'True':
        post_utils.gen_select_cluster_plot(electrode_num, num_clusters, clusters)

    ############################################################
    # Get unit details and load data
    ############################################################

    this_split_merge_signal = post_utils.split_merge_signal(clusters, args)
    split_or_merge = np.logical_or(this_split_merge_signal.split,
                                   this_split_merge_signal.merge)

    # If the user asked to split/re-cluster, 
    # ask them for the clustering parameters and perform clustering
    if this_split_merge_signal.split: 
        ##############################
        ## Split sequence
        ##############################
        # Get clustering parameters from user
        continue_bool, n_clusters, n_iter, thresh, n_restarts = \
                post_utils.get_clustering_params()
        if not continue_bool: continue

        # Make data array to be put through the GMM - 5 components: 
        # 3 PCs, scaled energy, amplitude
        # Clusters is a list, and for len(clusters) == 1,
        # the code below will always work
        this_cluster = np.where(predictions == int(clusters[0]))[0]

        data = post_utils.prepare_data(
                            this_cluster,
                            pca_slices,
                            energy,
                            amplitudes,
                            )

        # Cluster the data
        g = GaussianMixture(
                n_components = n_clusters, 
                covariance_type = 'full', 
                tol = thresh, 
                max_iter = n_iter, 
                n_init = n_restarts)
        g.fit(data)
    
        # Show the cluster plots if the solution converged
        if g.converged_:
            split_predictions = g.predict(data)
            post_utils.generate_cluster_plots(
                            split_predictions, 
                            spike_waveforms, 
                            spike_times, 
                            n_clusters, 
                            this_cluster)
        else:
            split_predictions = []
            print("Solution did not converge "\
                    "- try again with higher number of iterations "\
                    "or lower convergence criterion")
            continue


        # Ask the user for the split clusters they want to choose
        continue_bool, chosen_split = \
                post_utils.get_split_cluster_choice(n_clusters)
        if not continue_bool: continue

        # Once selections have been made, save data
        # Waveforms of originally chosen cluster
        cluster_inds = np.where(predictions == int(clusters[0]))[0] 
        fin_inds = np.concatenate(\
                [np.where(split_predictions == this_split)[0] \
                            for this_split in chosen_split])


        ############################################################ 
        unit_waveforms = spike_waveforms[cluster_inds, :]    
        # Subsetting this set of waveforms to include only the chosen split
        unit_waveforms = unit_waveforms[fin_inds]

        # Do the same thing for the spike times
        unit_times = spike_times[cluster_inds]
        unit_times = unit_times[fin_inds] 
        ############################################################ 


        # Plot selected clusters again after merging splits
        post_utils.generate_datashader_plot(
                unit_waveforms, 
                unit_times,
                title = 'Merged Splits',
                )
        plt.show()

    ##################################################

    # If only 1 cluster was chosen (and it wasn't split), 
    # add that as a new unit in /sorted_units. 
    # Ask if the isolated unit is an almost-SURE single unit
    elif not split_or_merge:
        ##############################
        ## Single cluster selected 
        ##############################
        fin_inds = np.where(predictions == int(clusters[0]))[0]

        unit_waveforms = spike_waveforms[fin_inds, :]
        unit_times = spike_times[fin_inds]


    elif this_split_merge_signal.merge: 
        ##############################
        ## Merge Sequence 
        ##############################
        # If the chosen units are going to be merged, merge them
        fin_inds = np.concatenate(\
                [np.where(predictions == int(cluster))[0] \
                for cluster in clusters])

        unit_waveforms = spike_waveforms[fin_inds, :]
        unit_times = spike_times[fin_inds]

        # Generate plot for merged unit
        violations1, violations2,_,_ = post_utils.generate_datashader_plot(
                unit_waveforms, 
                unit_times,
                title = 'Merged Unit',
                )
        plt.show()

        # Warn the user about the frequency of ISI violations 
        # in the merged unit
        continue_bool, proceed = \
                    post_utils.generate_violations_warning(
                            violations1,
                            violations2,
                            unit_times,
                            )
        if not continue_bool: continue

        # Create unit if the user agrees to proceed, 
        # else abort and go back to start of the loop 
        if not proceed:     
            continue


    ############################################################  
    # Finally, save the unit to the HDF5 file
    ############################################################  
    continue_bool = this_descriptor_handler.save_unit(
            unit_waveforms,
            unit_times,
            electrode_num,
            args,
            split_or_merge,
            )

    table.flush()
    hf5.flush()


    print('==== {} Complete ===\n'.format(unit_name))
    print('==== Iteration Ended ===\n')

# Sort unit_descriptor by unit_number
# This will be needed if sort_table is used, as using sort_table
# will add merge/split marked units first
this_descriptor_handler.sort_table_and_saved_units()

print('== Post-processing exiting ==')
# Close the hdf5 file
hf5.close()
