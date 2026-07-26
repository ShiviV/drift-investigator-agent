import os
import pandas as pd
import numpy as np
import math
from sklearn.preprocessing import OneHotEncoder
from sklearn.preprocessing import StandardScaler
from pickle import dump

def resolve_path(rel_path):
    if os.path.exists(rel_path):
        return rel_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    alt_path = os.path.normpath(os.path.join(script_dir, rel_path))
    if os.path.exists(alt_path) or os.path.exists(os.path.dirname(alt_path)):
        return alt_path
    project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    clean_rel = rel_path.replace("../", "")
    return os.path.normpath(os.path.join(project_root, clean_rel))

categorical_cols=['Gender',
       'Married', 'Dependents',
       'offer','Referred a Friend', 'Phone Service',
       'Multiple Lines', 'Internet Service', 'Internet Type',
        'Online Security', 'Online Backup',
       'Device Protection Plan', 'Premium Tech Support', 'Streaming TV',
       'Streaming Movies', 'Streaming Music', 'Unlimited Data',
       'Payment Method']

cts_cols=['Age','Number of Dependents',
       'roam_ic', 'roam_og', 'loc_og_t2t',
       'loc_og_t2m', 'loc_og_t2f', 'loc_og_t2c', 'std_og_t2t', 'std_og_t2m',
       'std_og_t2f', 'std_og_t2c', 'isd_og', 'spl_og', 'og_others',
       'loc_ic_t2t', 'loc_ic_t2m', 'loc_ic_t2f', 'std_ic_t2t', 'std_ic_t2m',
       'std_ic_t2f', 'std_ic_t2o', 'spl_ic', 'isd_ic', 'ic_others',
       'total_rech_amt', 'total_rech_data', 'vol_4g', 'vol_5g', 'arpu_5g',
       'arpu_4g', 'arpu', 'aug_vbc_5g', 'Number of Referrals','Satisfaction Score',
       'Streaming Data Consumption']

location_att=['zip_code','state', 'county', 'timezone', 'area_codes', 'country',
                  'latitude','longitude']

def map_month_to_quarter(month):
    if math.isnan(month): # Handle NaN values if present
        return None
    quarter = math.ceil(month / 3)
    return quarter



def process_data(df):
    '''
    The function cleans and processes data
    '''
    

    df.loc[(df['arpu_4g']=='Not Applicable') | (df['arpu_5g']=='Not Applicable'),'total_rech_data']=0
    
    df['total_rech_data']=df['total_rech_data'].fillna(df.loc[(df['arpu_4g']!='Not Applicable') | (df['arpu_5g']!='Not Applicable'),'total_rech_data'].mean())
    
    
    # fill missing values in Internet Type with 'Not Applicable'
    df['Internet Type'].fillna('Not Applicable', inplace=True)
    
    
    # add a new column 'total_recharge' by summing 'total_rech_amt' and 'total_rech_data'
    df.insert(loc=df.shape[1]-1,column='total_recharge',value=df['total_rech_amt']+df['total_rech_data'])
    
    #cheking percent of missing values in columns
    df_missing_columns = (round(((df.isnull().sum()/len(df.index))*100),2).to_frame('null')).sort_values('null', ascending=False)

    df=df.drop(columns=['night_pck_user', 'fb_user','Churn Category','Churn Reason', 'Customer Status'])

    df['arpu_4g']=df['arpu_4g'].replace('Not Applicable',0)
    df['arpu_5g']=df['arpu_5g'].replace('Not Applicable',0)

    df['arpu_4g']=df['arpu_4g'].astype(float)
    df['arpu_5g']=df['arpu_5g'].astype(float)

    out_path = resolve_path('../data/processed/processed_churn_data.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    
    df.insert(loc=1,column='Quarter of Joining',value=df['Month of Joining'].apply(lambda x: map_month_to_quarter(x)))
    df.insert(loc=1,column='Quarter',value= df['Month'].apply(lambda x: map_month_to_quarter(x)))
    

    telco=df.drop_duplicates(subset=['Customer ID','Quarter','Quarter of Joining'],keep='last')

    return telco
    





    
