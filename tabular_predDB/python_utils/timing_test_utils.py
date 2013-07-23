import numpy

import tabular_predDB.python_utils.data_utils as du
import tabular_predDB.python_utils.xnet_utils as xu
import tabular_predDB.LocalEngine as LE
import tabular_predDB.cython_code.State as State
from ARI_CrossCat import ARI_CrossCat

def get_generative_clustering(M_c, M_r, T,
                              data_inverse_permutation_indices,
                              num_clusters, num_views):
    # NOTE: this function only works because State.p_State doesn't use
    #       column_component_suffstats
    num_rows = len(T)
    num_cols = len(T[0])
    X_D_helper = numpy.repeat(range(num_clusters), (num_rows / num_clusters))
    gen_X_D = [
        X_D_helper[numpy.argsort(data_inverse_permutation_index)]
        for data_inverse_permutation_index in data_inverse_permutation_indices
        ]
    gen_X_L_assignments = numpy.repeat(range(num_views), (num_cols / num_views))
    # initialize to generate an X_L to manipulate
    local_engine = LE.LocalEngine()
    M_c, M_r, bad_X_L, bad_X_D = local_engine.initialize(M_c, M_r, T,
                                                         initialization='apart')
    bad_X_L['column_partition']['assignments'] = gen_X_L_assignments
    # manually constrcut state in in generative configuration
    state = State.p_State(M_c, T, bad_X_L, gen_X_D)
    gen_X_L = state.get_X_L()
    gen_X_D = state.get_X_D()
    # run inference on hyperparameters to leave them in a reasonable state
    kernel_list = (
        'row_partition_hyperparameters',
        'column_hyperparameters',
        'column_partition_hyperparameter',
        )
    gen_X_L, gen_X_D = local_engine.analyze(M_c, T, gen_X_L, gen_X_D, n_steps=1,
                                            kernel_list=kernel_list)
    #
    return gen_X_L, gen_X_D

def generate_clean_state(gen_seed, num_clusters,
                         num_cols, num_rows, num_splits,
                         max_mean=10, max_std=1,
                         plot=False):
    # generate the data
    T, M_r, M_c, data_inverse_permutation_indices = \
        du.gen_factorial_data_objects(gen_seed, num_clusters,
                                      num_cols, num_rows, num_splits,
                                      max_mean=10, max_std=1,
                                      send_data_inverse_permutation_indices=True)
    # recover generative clustering
    X_L, X_D = get_generative_clustering(M_c, M_r, T,
                                         data_inverse_permutation_indices,
                                         num_clusters, num_splits)
    return T, M_c, M_r, X_L, X_D

def generate_hadoop_dicts(which_kernels, X_L, X_D, args_dict):
    for which_kernel in which_kernels:
        kernel_list = (which_kernel, )
        dict_to_write = dict(X_L=X_L, X_D=X_D)
        dict_to_write.update(args_dict)
        # must write kernel_list after update
        dict_to_write['kernel_list'] = kernel_list
        yield dict_to_write

def write_hadoop_input(input_filename, X_L, X_D, n_steps, SEED):
    # prep settings dictionary
    time_analyze_args_dict = xu.default_analyze_args_dict
    time_analyze_args_dict['command'] = 'time_analyze'
    time_analyze_args_dict['SEED'] = SEED
    time_analyze_args_dict['n_steps'] = n_steps
    # one kernel per line
    all_kernels = State.transition_name_to_method_name_and_args.keys()
    n_tasks = 0
    with open(input_filename, 'w') as out_fh:
        dict_generator = generate_hadoop_dicts(all_kernels, X_L, X_D, time_analyze_args_dict)
        for dict_to_write in dict_generator:
            xu.write_hadoop_line(out_fh, key=dict_to_write['SEED'], dict_to_write=dict_to_write)
            n_tasks += 1
    return n_tasks


def truth_from_permute_indices(data_inverse_permutation_indices, num_rows,num_cols,num_views, num_clusters):
    # We assume num_rows is divisible by num_clusters and num_cols is divisible by num_views
    num_cols_per_view = num_cols/num_views
    view_assignments = []
    for viewindx in range(num_views):
        view_assignments = view_assignments + [viewindx]*num_cols_per_view

    num_rows_per_cluster = num_rows/num_clusters
    
    reference_list = []
    for clusterindx in range(num_clusters):
        reference_list = reference_list + [clusterindx]*num_rows_per_cluster
        
    X_D_truth = []
    for viewindx in range(num_views):
        X_D_truth.append([a for (b,a) in sorted(zip(data_inverse_permutation_indices[viewindx], reference_list))])
        
    X_D_truth = numpy.asarray(X_D_truth)
    X_D_truth = X_D_truth.T
    X_D_truth = X_D_truth.tolist()
        
    return view_assignments, X_D_truth

def multi_chain_ARI(X_L_list, X_D_List, view_assignment_truth, X_D_truth):
    ari_table = 0
    ari_views = 0
    num_chains = len(X_L_list)
    for chainindx in range(num_chains):
        view_assignments = X_L_list[chainindx]['column_partition']['assignments']
        curr_ari_table, curr_ari_views = ARI_CrossCat(view_assignments, X_D_List[chainindx], view_assignment_truth, X_D_truth)
        ari_table = ari_table + curr_ari_table
        ari_views = ari_views + curr_ari_views

    ari_table = ari_table/float(num_chains)
    ari_views = ari_views/float(num_chains)
    return ari_table, ari_views
         
