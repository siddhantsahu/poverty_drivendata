"""
Module to fit estimators and perform local cross-validation.
"""
import os
import logging

import numpy as np
import pandas as pd
from hyperopt import hp, fmin, tpe, Trials, space_eval
from xgboost import XGBClassifier
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Imputer

from src import DATA_DIR
from src.features.build_features import get_cols, le_columns


def prepare_data(df):
    """Drop columns, build features, impute missing values and return X and y,
    for training."""
    cat_cols, cols_to_drop = get_cols(df)
    df = df.pipe(le_columns, cat_cols)
    feature_columns = set(df.columns) - set(['id', 'country', 'poor']) - set(cols_to_drop)
    logging.debug('Before any feature selection, %s columns have been chosen as features',
                  len(feature_columns))
    X = df.loc[:, feature_columns].as_matrix()
    try:
        y = df.loc[:, 'poor'].as_matrix()
    except KeyError:
        y = None
    return X, y


def _estimate_local_cv(X, y):
    """Estimate of the score using 2x5, i.e. nested cross-validation strategies."""
    pipe = Pipeline([('clf', XGBClassifier(objective='binary:logistic'))])
    space = {}
    space['clf__max_depth'] = 5 + hp.randint('clf__max_depth', 5)   # (5, 10)
    space['clf__learning_rate'] = hp.uniform('clf__learning_rate', 0.01, 3.0)
    space['clf__n_estimators'] = 70 + 5*hp.randint('clf__n_estimators', 10) # 50:5:100
    space['clf__gamma'] = hp.loguniform('clf__gamma', 0.1, 1.0)
    space['clf__min_child_weight'] = 1 + hp.randint('clf__min_child_weight', 9) # (2, 10)
    space['clf__max_delta_step'] = hp.uniform('clf__max_delta_step', 0.0, 0.1)
    space['clf__subsample'] = hp.uniform('clf__subsample', 0.5, 1.0)
    space['clf__colsample_bytree'] = hp.uniform('clf__colsample_bytree', 0.5, 1.)

    def objective(params):
        """Objective is to minimize log_loss. So, output log_loss scores."""
        pipe.set_params(**params)
        scores = cross_val_score(pipe, X, y, scoring='neg_log_loss', cv=2, n_jobs=-1)
        return -1.0 * scores.mean()

    # to store details of each iteration
    # Note: with MongoTrials() as mentioned in http://bit.ly/2miT1Uc
    # custom objective functions don't work because of pickling errors
    trials = Trials()

    # run hyperparameter search using tpe algorithm
    best = fmin(objective, space, algo=tpe.suggest, max_evals=50, trials=trials, verbose=3)

    # get values of optimal parameters
    best_params = space_eval(space, best)
    return pipe, best_params, objective(best_params)


def cv_setup(country):
    """Helper function to return the cv scores for a country. Overall log_loss is mean
    of log_loss scores of all countries."""
    df = pd.read_csv(os.path.join(DATA_DIR, 'raw', '{}_hhold_train.csv'.format(country)))
    X, y = prepare_data(df)
    pipe, best_params, score = _estimate_local_cv(X, y)
    logging.debug('Local CV score for country %s is %s', country, score)
    logging.debug('Optimal parameters: %s', best_params)
    pipe.set_params(**best_params)
    pipe = pipe.fit(X, y)
    return pipe, best_params, score
