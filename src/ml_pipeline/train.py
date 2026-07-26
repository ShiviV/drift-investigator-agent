import xgboost as xgb

def train_xgb_model(X_train, y_train, X_test, y_test, params, num_rounds):
    """
    Trains an XGBoost model and returns the trained model object.

    Args:
        X_train (numpy array or pandas dataframe): The training data features.
        y_train (numpy array or pandas series): The training data labels.
        X_test (numpy array or pandas dataframe): The test data features.
        y_test (numpy array or pandas series): The test data labels.
        params (dict): XGBoost model hyperparameters.
        num_rounds (int): Number of boosting rounds to perform.

    Returns:
        Trained XGBoost model object.
    """
    # Convert training and test sets to DMatrix
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)

    # Train model
    xgbmodel = xgb.train(params, dtrain, num_rounds)

    return xgbmodel, dtrain, dtest
