import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd())) if str(Path.cwd()) not in sys.path else None
from _bp_predictor import BloodPresurePredictor
from _utils import log_exp, get_unique_healthCodes, average_dicts, strat_data_split, historical_BP
from collections import defaultdict
import os
import pandas as pd
import json

def train_personalized(datapath, model, ntrees, n, key, target, log_path='', bootstrap=False, 
               bootstrap_size=0.8, aug='None', second_run=False, historical=True, exclude=[]):
    
    dataset = pd.read_csv(f'{datapath}/{aug}.csv')      # Load dataset with specified augmentations
    # Add historical blood pressure to the dataset if specified
    if historical:
        dataset = historical_BP(dataset, 3)
    
    # Split dataset into train and test sets of features and labels
    (x_train, y_train), (x_test, y_test) = strat_data_split(dataset, y_columns=target, key_cols=key, datapath=datapath)
    x_train_keys = x_train[key]
    x_test_keys = x_test[key]
    x_train = x_train.drop(key, axis=1)
    x_test = x_test.drop(key, axis=1)

    # Get baseline model by running on all users
    bp_predictor = BloodPresurePredictor(model, ntrees, target_cols=target, exlude_cols=exclude)
    bp_predictor.fit(x_train, y_train, bootstrap, bootstrap_size)

    # Get all unique healthCodes
    all_users = get_unique_healthCodes(dataset)

    # Initialize lists to store metrics results
    mae = defaultdict(list)
    mse = defaultdict(list)
    temp_feature_importances = []
    # Personalize the model for each user
    for user in all_users:
        tr_mask = x_train_keys.iloc[:, 0] == user
        test_mask = x_test_keys.iloc[:, 0] == user
        x_train_user, y_train_user = x_train[tr_mask], y_train[tr_mask]

        x_test_user, y_test_user = x_test[test_mask], y_test[test_mask]

        # Skips if there are no samples for the user
        if x_train_user.shape[0] < 1 or x_test_user.shape[0] < 1:
            continue

        else:
            bp_predictor.fine_tune(x_train_user, y_train_user)                   # Fit the personalized model
            bp_predictor.evaluate(x_test_user, y_test_user, fine_tuned=True)     # Evaluate the personalized model
            # Performs second run with top N features if specified
            if second_run:
                top_n = list(bp_predictor.feature_importances.keys())[:n]
                bp_predictor.fine_tune(x_train_user[top_n], y_train_user)
                bp_predictor.evaluate(x_test_user[top_n], y_test_user, fine_tuned=True)
            for bp_type in target:
                mae[bp_type].append(bp_predictor.mae[bp_type])
                mse[bp_type].append(bp_predictor.mse[bp_type])
            temp_feature_importances.append(bp_predictor.feature_importances)

            # Saves the model and the feature importances for each user
            dir_corr = Path.cwd()
            path_state = dir_corr/'personalized_model_states'/'model_states'
            path_feat = dir_corr/'personalized_model_states'/'feature_importances'
            if not os.path.exists(path_state):
                os.makedirs(path_state)
            if not os.path.exists(path_feat):
                os.makedirs(path_feat)
            for bp_type in target:
                bp_predictor.ftmodel[bp_type].save_model(f'{path_state}/{user}_{bp_type}.json')
            # Save dict of feature importances
            with open(f'{path_feat}/{user}.json', 'w') as f:
                f.write(str(bp_predictor.feature_importances))

    if len(mae) == 0:
        print('No testing samples')
        return
    
    # Average metrics for all users
    for bp_type in target:
        bp_predictor.mae[bp_type] = sum(mae[bp_type]) / len(mae[bp_type])
        bp_predictor.mse[bp_type] = sum(mse[bp_type]) / len(mse[bp_type])
    bp_predictor.feature_importances = average_dicts(temp_feature_importances)

    # log results
    log_exp(log_path, bp_predictor, aug=aug, n=n, second_run=second_run, bootstrap=bootstrap, 
            test_size=x_test.shape, historical=historical, personalized=True)


if __name__ == '__main__':
    dir_corr = Path.cwd()
    model_config = dir_corr/'configs'/'training'/'per-model_config.json'     # default path to the model config
    dataset_config = dir_corr/'configs'/'training'/'dataset_config.json'     # default path to the dataset config

    ############################### MODEL PARAMETERS ###############################
    with open(model_config) as f:
        model_config = json.load(f)
    n = model_config['n']                               # Number of most important features to display
    ntrees = model_config['ntrees']                     # Number of trees in the forest
    bootstrap = model_config['bootstrap']               # Whether to use bootstrap samples
    bootstrap_size = model_config['bootstrap_size']     # Portion of the dataset to sample for bootstrap
    historical = model_config['historical']             # Whether to use historical BP or not

    ############################### DATASET PARAMETERS ###############################
    with open(dataset_config) as f:
        dataset_config = json.load(f)
    datapath = dataset_config['datapath']  # Path of the dataset
    aug = dataset_config['aug']            # Type of augmentation to use
    key = dataset_config['key']            # Columns to use as key
    target = dataset_config['target']      # Columns to predict
    exclude = dataset_config['exclude']    # Columns to exclude from the feature importance analysis
    log_path = dataset_config['log_path']  # Path of file to log experiment results

    train_personalized(datapath, 'xgb', ntrees, n, key, target, log_path=log_path, bootstrap=bootstrap, 
                            bootstrap_size=bootstrap_size, aug=aug, historical=historical, exclude=exclude)