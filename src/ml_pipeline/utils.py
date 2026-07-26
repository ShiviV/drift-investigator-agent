import pandas as pd
from sklearn.preprocessing import OneHotEncoder
from sklearn.preprocessing import StandardScaler
from pickle import dump
from .processing import *



drop_cols=['Customer ID', 'Quarter', 'Quarter of Joining', 'Month',
       'Month of Joining', 'zip_code','Location ID', 'Service ID',
       'state', 'county', 'timezone', 'area_codes', 'country', 'latitude',
       'longitude','Status ID']



def split_and_encode_data(processed_data):
    '''
    The function splits the data and uses first two quarters leaving rest for feedback loop and encodes data for 
    model training.

    '''
    train_data=processed_data[(processed_data['Quarter of Joining']==1)&(processed_data['Quarter']==1)]
    test_data=processed_data[(processed_data['Quarter of Joining']==1)&(processed_data['Quarter']==2)]
    prediction_data=processed_data[(processed_data['Quarter of Joining']==2)&(processed_data['Quarter']==2)]

    
    train_data=train_data.drop(columns=drop_cols)
    test_data=test_data.drop(columns=drop_cols)

    
    X_train=train_data[train_data.columns[:-1]].copy()
    y_train=train_data[train_data.columns[-1]].copy()

    X_test=test_data[test_data.columns[:-1]].copy()
    y_test=test_data[test_data.columns[-1]].copy() 

    #fit encoder
    try:
        encoder = OneHotEncoder(sparse_output=False)
    except TypeError:
        encoder = OneHotEncoder(sparse=False)
    # train
    encoder.fit(X_train[categorical_cols])
    encoded_features = list(encoder.get_feature_names_out(categorical_cols))

    X_train[encoded_features] = encoder.transform(X_train[categorical_cols])
    # test
    X_test[encoded_features] = encoder.transform(X_test[categorical_cols])

    encoder_path = resolve_path('../data/raw/encoder.pkl')
    os.makedirs(os.path.dirname(encoder_path), exist_ok=True)
    dump(encoder, open(encoder_path, 'wb'))

    # drop original features
    X_train=X_train.drop(categorical_cols,axis=1)
    X_test=X_test.drop(categorical_cols,axis=1)

    # Instantiate scaler
    scaler = StandardScaler()

    # Scale Separate Columns
    # train
    X_train[cts_cols]  = scaler.fit_transform(X_train[cts_cols]) 
    # test

    X_test[cts_cols]  = scaler.transform(X_test[cts_cols])
    
    scaler_path = resolve_path('../data/raw/scaler.pkl')
    os.makedirs(os.path.dirname(scaler_path), exist_ok=True)
    dump(scaler, open(scaler_path, 'wb'))

    return prediction_data, X_train, y_train, X_test, y_test, encoder, scaler, encoded_features