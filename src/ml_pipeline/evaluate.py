import pandas as pd
from sklearn.metrics import f1_score, recall_score, confusion_matrix, roc_auc_score





# function modelling
#Columns needed to compare metrics
comparison_columns = ['Model_Name', 'Train_F1score', 'Train_Recall','Test_F1score', 'Test_Recall']

comparison_df = pd.DataFrame()

def evaluate_models(model_name, model_defined_var, X_train, y_train, X_test, y_test):
  ''' This function predicts and evaluates various models for clasification'''
  
  # train predictions
  y_train_pred = model_defined_var.predict(X_train)
  # train performance
  train_f1_score = f1_score(y_train,y_train_pred)
  train_recall = recall_score(y_train, y_train_pred)

  # test predictions
  y_pred = model_defined_var.predict(X_test)
  # test performance
  test_f1_score = f1_score(y_test,y_pred)
  test_recall = recall_score(y_test, y_pred)

  # Printing performance
  print("Train Results")
  print(f'F1 Score: {train_f1_score}')
  print(f'Recall Score: {train_recall}')
  print(f'Confusion Matrix: \n{confusion_matrix(y_train, y_train_pred)}')

  print(f'Area Under Curve: {roc_auc_score(y_train, y_train_pred)}')

  print(" ")

  print("Test Results")
  print(f'F1 Score: {test_f1_score}')
  print(f'Recall Score: {test_recall}')
  print(f'Confusion Matrix: \n{confusion_matrix(y_test, y_pred)}')

  print(f'Area Under Curve: {roc_auc_score(y_test, y_pred)}')

  
  #Saving our results
  global comparison_columns

  metric_scores = [model_name, train_f1_score, train_recall, test_f1_score, test_recall]
  final_dict = dict(zip(comparison_columns,metric_scores))

  return final_dict


#function to create the comparison table
final_list = []
def add_dic_to_final_df(final_dict):
  global final_list
  final_list.append(final_dict)
  global comparison_df
  comparison_df = pd.DataFrame(final_list, columns= comparison_columns)