import tensorflow as tf
import numpy as np
import shutil
import os
from datetime import datetime
from .utils import TORNASOLE_TF_HOOK_TESTS_DIR
from tornasole.core.json_config import TORNASOLE_CONFIG_FILE_PATH_ENV_STR

import tornasole.tensorflow as ts
from tornasole.tensorflow import reset_collections
from tornasole.tensorflow.hook import TornasoleHook
from tornasole.trials import create_trial


def help_test_mnist(path, save_config=None, hook=None):
    trial_dir = path
    tf.reset_default_graph()
    if hook is None:
        reset_collections()

    def cnn_model_fn(features, labels, mode):
        """Model function for CNN."""
        # Input Layer
        input_layer = tf.reshape(features["x"], [-1, 28, 28, 1])

        # Convolutional Layer #1
        conv1 = tf.layers.conv2d(
            inputs=input_layer,
            filters=32,
            kernel_size=[5, 5],
            padding="same",
            activation=tf.nn.relu)

        # Pooling Layer #1
        pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)

        # Convolutional Layer #2 and Pooling Layer #2
        conv2 = tf.layers.conv2d(
            inputs=pool1,
            filters=64,
            kernel_size=[5, 5],
            padding="same",
            activation=tf.nn.relu)
        pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)

        # Dense Layer
        pool2_flat = tf.reshape(pool2, [-1, 7 * 7 * 64])
        dense = tf.layers.dense(inputs=pool2_flat, units=1024, activation=tf.nn.relu)
        dropout = tf.layers.dropout(
            inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)

        # Logits Layer
        logits = tf.layers.dense(inputs=dropout, units=10)

        predictions = {
            # Generate predictions (for PREDICT and EVAL mode)
            "classes": tf.argmax(input=logits, axis=1),
            # Add `softmax_tensor` to the graph. It is used for PREDICT and by the
            # `logging_hook`.
            "probabilities": tf.nn.softmax(logits, name="softmax_tensor")
        }

        if mode == tf.estimator.ModeKeys.PREDICT:
            return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

        # Calculate Loss (for both TRAIN and EVAL modes)
        loss = tf.losses.sparse_softmax_cross_entropy(labels=labels, logits=logits)

        # Configure the Training Op (for TRAIN mode)
        if mode == tf.estimator.ModeKeys.TRAIN:
            optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.001)
            optimizer = ts.TornasoleOptimizer(optimizer)
            train_op = optimizer.minimize(
                loss=loss,
                global_step=tf.train.get_global_step())
            return tf.estimator.EstimatorSpec(mode=mode, loss=loss, train_op=train_op)

        # Add evaluation metrics (for EVAL mode)
        eval_metric_ops = {
            "accuracy": tf.metrics.accuracy(
                labels=labels, predictions=predictions["classes"])
        }
        return tf.estimator.EstimatorSpec(
            mode=mode, loss=loss, eval_metric_ops=eval_metric_ops)

    # Load training and eval data
    ((train_data, train_labels),
     (eval_data, eval_labels)) = tf.keras.datasets.mnist.load_data()

    train_data = train_data / np.float32(255)
    train_labels = train_labels.astype(np.int32)  # not required

    eval_data = eval_data / np.float32(255)
    eval_labels = eval_labels.astype(np.int32)  # not required

    mnist_classifier = tf.estimator.Estimator(
        model_fn=cnn_model_fn, model_dir="/tmp/mnist_convnet_model")

    train_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": train_data},
        y=train_labels,
        batch_size=100,
        num_epochs=None,
        shuffle=True)

    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data},
        y=eval_labels,
        num_epochs=1,
        shuffle=False)
    if hook is None:
        hook = ts.TornasoleHook(out_dir=trial_dir,
                                save_config=save_config)
    hook.set_mode(ts.modes.TRAIN)
    # train one step and display the probabilties
    mnist_classifier.train(
        input_fn=train_input_fn,
        steps=10,
        hooks=[hook])

    hook.set_mode(ts.modes.EVAL)
    mnist_classifier.evaluate(input_fn=eval_input_fn, hooks=[hook])

    hook.set_mode(ts.modes.TRAIN)
    mnist_classifier.train(
        input_fn=train_input_fn,
        steps=20,
        hooks=[hook])

    tr = create_trial(trial_dir)
    return tr


def test_mnist_local():
    run_id = 'trial_' + datetime.now().strftime('%Y%m%d-%H%M%S%f')
    trial_dir = os.path.join(TORNASOLE_TF_HOOK_TESTS_DIR, run_id)
    tr = help_test_mnist(trial_dir, ts.SaveConfig(save_interval=2))
    assert len(tr.available_steps()) == 55
    assert len(tr.available_steps(mode=ts.modes.TRAIN)) == 15
    assert len(tr.available_steps(mode=ts.modes.EVAL)) == 40
    assert len(tr.tensors()) == 16
    shutil.rmtree(trial_dir)


def test_mnist_local_json():
    out_dir = 'newlogsRunTest1/test_mnist_local_json_config'
    shutil.rmtree(out_dir, ignore_errors=True)
    os.environ[TORNASOLE_CONFIG_FILE_PATH_ENV_STR] = 'tests/tensorflow/hooks/test_json_configs/test_mnist_local.json'
    hook = TornasoleHook.hook_from_config()
    tr = help_test_mnist(path=out_dir, hook=hook)
    assert len(tr.available_steps()) == 55
    assert len(tr.available_steps(mode=ts.modes.TRAIN)) == 15
    assert len(tr.available_steps(mode=ts.modes.EVAL)) == 40
    assert len(tr.tensors()) == 16
    shutil.rmtree(out_dir, ignore_errors=True)


def test_mnist_s3():
    run_id = 'trial_' + datetime.now().strftime('%Y%m%d-%H%M%S%f')
    trial_dir = 's3://tornasole-testing/tornasole_tf/hooks/estimator_modes/' + run_id
    tr = help_test_mnist(trial_dir, ts.SaveConfig(save_interval=2))
    assert len(tr.available_steps()) == 55
    assert len(tr.available_steps(mode=ts.modes.TRAIN)) == 15
    assert len(tr.available_steps(mode=ts.modes.EVAL)) == 40
    assert len(tr.tensors()) == 16


def test_mnist_local_multi_save_configs():
    run_id = 'trial_' + datetime.now().strftime('%Y%m%d-%H%M%S%f')
    trial_dir = os.path.join(TORNASOLE_TF_HOOK_TESTS_DIR, run_id)
    tr = help_test_mnist(trial_dir, {ts.modes.TRAIN: ts.SaveConfig(save_interval=2),
                                     ts.modes.EVAL: ts.SaveConfig(save_interval=1)})
    assert len(tr.available_steps()) == 94
    assert len(tr.available_steps(mode=ts.modes.TRAIN)) == 15
    assert len(tr.available_steps(mode=ts.modes.EVAL)) == 79
    assert len(tr.tensors()) == 16
    shutil.rmtree(trial_dir)


def test_mnist_s3_multi_save_configs():
    run_id = 'trial_' + datetime.now().strftime('%Y%m%d-%H%M%S%f')
    trial_dir = 's3://tornasole-testing/tornasole_tf/hooks/estimator_modes/' + run_id
    tr = help_test_mnist(trial_dir, {ts.modes.TRAIN: ts.SaveConfig(save_interval=2),
                                     ts.modes.EVAL: ts.SaveConfig(save_interval=1)})
    assert len(tr.available_steps()) == 94
    assert len(tr.available_steps(mode=ts.modes.TRAIN)) == 15
    assert len(tr.available_steps(mode=ts.modes.EVAL)) == 79
    assert len(tr.tensors()) == 16


def test_mnist_local_multi_save_configs_json():
    out_dir = 'newlogsRunTest1/test_save_config_modes_hook_config'
    shutil.rmtree(out_dir, ignore_errors=True)
    os.environ[
        TORNASOLE_CONFIG_FILE_PATH_ENV_STR] = 'tests/tensorflow/hooks/test_json_configs/test_save_config_modes_hook_config.json'
    hook = ts.TornasoleHook.hook_from_config()
    tr = help_test_mnist(out_dir, hook=hook)
    assert len(tr.available_steps()) == 94
    assert len(tr.available_steps(mode=ts.modes.TRAIN)) == 15
    assert len(tr.available_steps(mode=ts.modes.EVAL)) == 79
    assert len(tr.tensors()) == 16
    shutil.rmtree(out_dir)
