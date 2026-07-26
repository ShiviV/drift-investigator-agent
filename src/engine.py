import pandas as pd
import numpy as np
import xgboost as xgb
from ml_pipeline.processing import process_data
from ml_pipeline.utils import split_and_encode_data
from ml_pipeline.train import train_xgb_model
from ml_pipeline.evaluate import *
from ml_pipeline.drift import inference_pipeline_with_label, pred_cat_cols, pred_cts_cols, preprocess_steps




import os

def resolve_path(rel_path):
    if os.path.exists(rel_path):
        return rel_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    alt_path = os.path.normpath(os.path.join(script_dir, rel_path))
    if os.path.exists(alt_path) or os.path.exists(os.path.dirname(alt_path)):
        return alt_path
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    clean_rel = rel_path.replace("../", "")
    return os.path.normpath(os.path.join(project_root, clean_rel))

# 1. Read Data
df = pd.read_csv(resolve_path("../data/raw/Telecom_Data.csv"))
print("Data Read!")

# 2. Process Data
processed_df = process_data(df)
print("Data Processed!")

# 3. Split and Encode Data
prediction_data, X_train, y_train, X_test, y_test, encoder, scaler, encoded_features = split_and_encode_data(processed_df)

# 4. Train Model
params = {'objective': 'multi:softmax', 'num_class': 2}
num_rounds = 30

xgbmodel, dtrain, dtest = train_xgb_model(X_train, y_train, X_test, y_test, params, num_rounds)
print("Base Model Trained")

# 5. Evaluate
xgb_results = evaluate_models("XGB", xgbmodel, dtrain, y_train, dtest, y_test)
add_dic_to_final_df(xgb_results)
xgbmodel.save_model(resolve_path('../models/xgb_base.model'))
print("Base Model Saved!")

# 6. Check Drift and Retrain if Required
# actual values
label_check_data=X_train.copy()
label_check_data['Churn Value']=y_train

# Report of data drift with label
print("Results on Test Data")
d2_drift,model_retrain,pred=inference_pipeline_with_label(inference_data=prediction_data[prediction_data.columns[:-1]],reference_data=label_check_data,job_id='1njkwna',trained_model=xgbmodel,predictors_cols=pred_cat_cols+pred_cts_cols,target_col_name='Churn Value',target_value=prediction_data['Churn Value'], encoded_features=encoded_features, encoder=encoder,scaler=scaler)

retrain_rounds = 100

if d2_drift['retrain']:
    clean_prediction_data=preprocess_steps(prediction_data[prediction_data.columns[:-1]], encoded_features, encoder, scaler)
    drift_train=pd.concat([X_train,clean_prediction_data],ignore_index=True)
    drift_label=pd.concat([y_train,prediction_data['Churn Value']],ignore_index=True)

    xgb_retrained = xgb.train(params, xgb.DMatrix(drift_train, label=drift_label), num_boost_round=num_rounds)

elif model_retrain:
    print("Model Retraining Started!")
    misclassified = prediction_data['Churn Value'] != pred
    feedback_X = prediction_data[misclassified][prediction_data.columns[:-1]]
    feedback_y = prediction_data[misclassified]['Churn Value']
    
    # Preprocess the combined training data
    feedback_processed = preprocess_steps(feedback_X, encoded_features, encoder, scaler)

     # Append misclassified feedback data to original training data
    X_train_all = pd.concat([X_train, feedback_processed], ignore_index=True)
    y_train_all = pd.concat([y_train, feedback_y], ignore_index=True)
    
    # Retrain the model on the combined training data
    xgb_retrained = xgb.train(params, xgb.DMatrix(X_train_all, label=y_train_all), 
                         xgb_model=resolve_path('../models/xgb_base.model'), num_boost_round=retrain_rounds)
else:
    xgb_retrained = xgbmodel
    


print("Results on the Test Data with Retrained Model")
# Check after retraining
d3_drift,model2_retrain,pred2=inference_pipeline_with_label(inference_data=prediction_data[prediction_data.columns[:-1]],reference_data=label_check_data,job_id='6378njkwna',trained_model=xgb_retrained,predictors_cols=pred_cat_cols+pred_cts_cols,target_col_name='Churn Value',target_value=prediction_data['Churn Value'], encoded_features=encoded_features, encoder=encoder,scaler=scaler)
# Save the model
xgb_retrained.save_model(resolve_path('../models/xgb_retrained.model'))