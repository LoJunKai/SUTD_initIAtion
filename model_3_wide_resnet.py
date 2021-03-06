# Import libraries

import random
import numpy as np
import scipy.io
import matplotlib.pyplot as plt
import os

# %matplotlib inline

import keras
from keras.models import Model
from keras.utils import to_categorical, get_file
from keras.callbacks import ModelCheckpoint, EarlyStopping, ReduceLROnPlateau, Callback
from keras.preprocessing.image import ImageDataGenerator
from keras.optimizers import SGD
import sklearn.model_selection

from keras.layers import Input, Add, Activation, Dropout, Flatten, Dense
from keras.layers.convolutional import Conv2D, MaxPooling2D, AveragePooling2D
from keras.layers.normalization import BatchNormalization
from keras.regularizers import l2
from keras import backend as K

# Loading the files - 1393553986B = 1.30GB

train_mat = keras.utils.get_file("extra_32x32.mat", "http://ufldl.stanford.edu/housenumbers/extra_32x32.mat")
test_mat = keras.utils.get_file("test_32x32.mat", "https://s3-ap-southeast-1.amazonaws.com/deeplearning-iap-material/test_32x32.mat")

# Loading the files
train_array = scipy.io.loadmat(train_mat)
num_images = train_array["X"].shape[-1]

# Take the first 200k labels
list_labels = train_array["y"][:100000].reshape((num_images-431131))
list_images = []

# Do the same for images
for i in range(num_images-431131):
    image = train_array["X"][:,:,:,i].reshape((32,32,3))
    list_images.append(image)

# Formatting the images
list_labels = np.asarray(list_labels, dtype='int32')
list_images = np.asarray(list_images)

# One-hot encoding
list_labels = to_categorical(list_labels)

# Take out the extra column which one-hot encoding introduced 
# This is because to_categorical starts from index 0 while labels start from index 1
list_labels = np.delete(list_labels, np.s_[0], axis=1)   

print(list_images.shape, list_labels.shape)

# Create WRN model - https://github.com/titu1994/Wide-Residual-Networks/blob/master/wide_residual_network.py
# Credits to Sergey Zagoruyko and Nikos Komodakis for the research and titu1994 for the implementation 

weight_decay = 0.0005

def initial_conv(input):
    x = Conv2D(16, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(input)

    channel_axis = 1 if K.image_data_format() == "channels_first" else -1

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)
    return x


def expand_conv(init, base, k, strides=(1, 1)):
    x = Conv2D(base * k, (3, 3), padding='same', strides=strides, kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(init)

    channel_axis = 1 if K.image_data_format() == "channels_first" else -1

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)

    x = Conv2D(base * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    skip = Conv2D(base * k, (1, 1), padding='same', strides=strides, kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(init)

    m = Add()([x, skip])

    return m


def conv1_block(input, k=1, dropout=0.0):
    init = input

    channel_axis = 1 if K.image_data_format() == "channels_first" else -1

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(input)
    x = Activation('relu')(x)
    x = Conv2D(16 * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    if dropout > 0.0: x = Dropout(dropout)(x)

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)
    x = Conv2D(16 * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    m = Add()([init, x])
    return m

def conv2_block(input, k=1, dropout=0.0):
    init = input

    channel_axis = 1 if K.image_dim_ordering() == "th" else -1

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(input)
    x = Activation('relu')(x)
    x = Conv2D(32 * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    if dropout > 0.0: x = Dropout(dropout)(x)

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)
    x = Conv2D(32 * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    m = Add()([init, x])
    return m

def conv3_block(input, k=1, dropout=0.0):
    init = input

    channel_axis = 1 if K.image_dim_ordering() == "th" else -1

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(input)
    x = Activation('relu')(x)
    x = Conv2D(64 * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    if dropout > 0.0: x = Dropout(dropout)(x)

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)
    x = Conv2D(64 * k, (3, 3), padding='same', kernel_initializer='he_normal',
                      kernel_regularizer=l2(weight_decay),
                      use_bias=False)(x)

    m = Add()([init, x])
    return m

def create_wide_residual_network(input_dim, nb_classes=100, N=2, k=1, dropout=0.0, verbose=1):

    channel_axis = 1 if K.image_data_format() == "channels_first" else -1

    ip = Input(shape=input_dim)

    x = initial_conv(ip)
    nb_conv = 4

    x = expand_conv(x, 16, k)
    nb_conv += 2

    for i in range(N - 1):
        x = conv1_block(x, k, dropout)
        nb_conv += 2

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)

    x = expand_conv(x, 32, k, strides=(2, 2))
    nb_conv += 2

    for i in range(N - 1):
        x = conv2_block(x, k, dropout)
        nb_conv += 2

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)

    x = expand_conv(x, 64, k, strides=(2, 2))
    nb_conv += 2

    for i in range(N - 1):
        x = conv3_block(x, k, dropout)
        nb_conv += 2

    x = BatchNormalization(axis=channel_axis, momentum=0.1, epsilon=1e-5, gamma_initializer='uniform')(x)
    x = Activation('relu')(x)

    x = AveragePooling2D((8, 8))(x)
    x = Flatten()(x)

    x = Dense(nb_classes, kernel_regularizer=l2(weight_decay), activation='softmax')(x)

    model = Model(ip, x)

    if verbose: print("Wide Residual Network-%d-%d created." % (nb_conv, k))
    return model

# get image shape
init = list_images[0].shape

# Instantiate model
model = create_wide_residual_network(init, nb_classes=10, N=2, k=2, dropout=0.0)
"""
Creates a Wide Residual Network with specified parameters
:param input: Input Keras object
:param nb_classes: Number of output classes
:param N: Depth of the network. Compute N = (n - 4) / 6.
          Example : For a depth of 16, n = 16, N = (16 - 4) / 6 = 2
          Example2: For a depth of 28, n = 28, N = (28 - 4) / 6 = 4
          Example3: For a depth of 40, n = 40, N = (40 - 4) / 6 = 6
:param k: Width of the network.
:param dropout: Adds dropout if value is greater than 0.0
:param verbose: Debug info to describe created WRN
:return:
wrn_28_10
"""

# Instantiate optimizer
sgd = SGD(lr=0.1, momentum=0.9, nesterov=False)
model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

model.summary()

# Customise ReduceLROnPlateau callback to load model weights after reducing LR 
# Copied from source code - https://github.com/keras-team/keras/blob/master/keras/callbacks.py
# Added code at the bottom

class Custom_ReduceLROnPlateau(Callback):
    """Reduce learning rate when a metric has stopped improving.
    Models often benefit from reducing the learning rate by a factor
    of 2-10 once learning stagnates. This callback monitors a
    quantity and if no improvement is seen for a 'patience' number
    of epochs, the learning rate is reduced.
    # Example
    ```python
    reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.2,
                                  patience=5, min_lr=0.001)
    model.fit(X_train, Y_train, callbacks=[reduce_lr])
    ```
    # Arguments
        monitor: quantity to be monitored.
        factor: factor by which the learning rate will
            be reduced. new_lr = lr * factor
        patience: number of epochs with no improvement
            after which learning rate will be reduced.
        verbose: int. 0: quiet, 1: update messages.
        mode: one of {auto, min, max}. In `min` mode,
            lr will be reduced when the quantity
            monitored has stopped decreasing; in `max`
            mode it will be reduced when the quantity
            monitored has stopped increasing; in `auto`
            mode, the direction is automatically inferred
            from the name of the monitored quantity.
        min_delta: threshold for measuring the new optimum,
            to only focus on significant changes.
        cooldown: number of epochs to wait before resuming
            normal operation after lr has been reduced.
        min_lr: lower bound on the learning rate.
    """

    def __init__(self, monitor='val_loss', factor=0.1, patience=10,
                 verbose=0, mode='auto', min_delta=1e-4, cooldown=0, min_lr=0,
                 **kwargs):
        super(Custom_ReduceLROnPlateau, self).__init__()

        self.monitor = monitor
        if factor >= 1.0:
            raise ValueError('ReduceLROnPlateau '
                             'does not support a factor >= 1.0.')
        if 'epsilon' in kwargs:
            min_delta = kwargs.pop('epsilon')
            warnings.warn('`epsilon` argument is deprecated and '
                          'will be removed, use `min_delta` instead.')
        self.factor = factor
        self.min_lr = min_lr
        self.min_delta = min_delta
        self.patience = patience
        self.verbose = verbose
        self.cooldown = cooldown
        self.cooldown_counter = 0  # Cooldown counter.
        self.wait = 0
        self.best = 0
        self.mode = mode
        self.monitor_op = None
        self._reset()

    def _reset(self):
        """Resets wait counter and cooldown counter.
        """
        if self.mode not in ['auto', 'min', 'max']:
            warnings.warn('Learning Rate Plateau Reducing mode %s is unknown, '
                          'fallback to auto mode.' % (self.mode),
                          RuntimeWarning)
            self.mode = 'auto'
        if (self.mode == 'min' or
           (self.mode == 'auto' and 'acc' not in self.monitor)):
            self.monitor_op = lambda a, b: np.less(a, b - self.min_delta)
            self.best = np.Inf
        else:
            self.monitor_op = lambda a, b: np.greater(a, b + self.min_delta)
            self.best = -np.Inf
        self.cooldown_counter = 0
        self.wait = 0

    def on_train_begin(self, logs=None):
        self._reset()

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        logs['lr'] = K.get_value(self.model.optimizer.lr)
        current = logs.get(self.monitor)
        if current is None:
            warnings.warn(
                'Reduce LR on plateau conditioned on metric `%s` '
                'which is not available. Available metrics are: %s' %
                (self.monitor, ','.join(list(logs.keys()))), RuntimeWarning
            )

        else:
            if self.in_cooldown():
                self.cooldown_counter -= 1
                self.wait = 0

            if self.monitor_op(current, self.best):
                self.best = current
                self.wait = 0
            elif not self.in_cooldown():
                self.wait += 1
                if self.wait >= self.patience:
                    old_lr = float(K.get_value(self.model.optimizer.lr))
                    if old_lr > self.min_lr:
                        new_lr = old_lr * self.factor
                        new_lr = max(new_lr, self.min_lr)
                        K.set_value(self.model.optimizer.lr, new_lr)
                        
                        # Load weights
                        model.load_weights(checkpoint_path)
                        
                        if self.verbose > 0:
                            print('\nEpoch %05d: ReduceLROnPlateau reducing '
                                  'learning rate to %s.' % (epoch + 1, new_lr))
                        self.cooldown_counter = self.cooldown
                        self.wait = 0

    def in_cooldown(self):
        return self.cooldown_counter > 0

# Set up checkpoint path
checkpoint_path = 'weights.best.cnn.hdf5'

# Instantiate callbacks
# custom_reducelronplateau = Custom_ReduceLROnPlateau(monitor='val_loss', factor=0.1, patience=2, verbose=1, min_delta=0.0001, min_lr=0)
custom_reducelronplateau = ReduceLROnPlateau(monitor='val_loss', factor=0.1, patience=2, verbose=1, min_delta=0.0001, min_lr=0)

callbacks = [EarlyStopping(monitor='val_loss', patience=4),
             ModelCheckpoint(filepath=checkpoint_path, monitor='val_loss', save_best_only=True),
             custom_reducelronplateau]

# Instantiate ImageDataGenerator to normalize image and split dataset into train and validation sets
train_datagen = ImageDataGenerator(featurewise_center=True, 
                                   featurewise_std_normalization=True,
                                   samplewise_center=False, 
                                   samplewise_std_normalization=False, 
                                   validation_split=0.2)

# fit the generator to the dataset to calculate dataset mean and sd
train_datagen.fit(list_images)

# Point the generator to the dataset
train_generator = train_datagen.flow(list_images, list_labels, batch_size=128, subset='training')
valid_generator = train_datagen.flow(list_images, list_labels, batch_size=128, subset='validation')

# Train the model
model_log = model.fit_generator(train_generator, 
                        validation_data=valid_generator, 
                        steps_per_epoch=len(train_generator), 
                        validation_steps=len(valid_generator), 
                        epochs=100,
                        verbose=2,
                        callbacks=callbacks)

# Plot graphs

plt.plot(model_log.history['acc'])
plt.plot(model_log.history['val_acc'])
plt.title('Accuracy (Higher Better)')
plt.ylabel('Accuracy')
plt.xlabel('Epoch')
plt.legend(['train', 'validation'], loc='upper left')
plt.show()

plt.plot(model_log.history['loss'])
plt.plot(model_log.history['val_loss'])
plt.title('Loss (Lower Better)')
plt.ylabel('Loss')
plt.xlabel('Epoch')
plt.legend(['train', 'validation'], loc='upper left')
plt.show()

# Testing

from sklearn.metrics import accuracy_score

test_array = scipy.io.loadmat(test_mat)
print(test_array.keys())

print("Test set has the following shape:")
test_array["X"].shape, test_array["y"].shape

num_images = test_array["y"].shape[0]

test_labels = test_array["y"].reshape((num_images))
test_images = []

for i in range(num_images):
    image = test_array["X"][:,:,:,i].reshape((32,32,3))
    test_images.append(image)
    
test_labels = np.asarray(test_labels, dtype='int32')
test_images = np.asarray(test_images)

# Preprocessing - standardization
test_images = (test_images - train_datagen.mean) / train_datagen.std

print("test_images:", test_images.shape)

test_labels = to_categorical(test_labels)

# Preprocessing - removal of the empty column
test_labels = np.delete(test_labels, np.s_[0], axis=1) 

test_labels_index = np.argmax(test_labels, axis=1)
test_preds = model.predict(test_images)
test_preds_class = np.argmax(test_preds,axis=1)
print("Test set accuracy score:", accuracy_score(test_labels_index, test_preds_class))


'''

Everything the same except dataset=300000, k=4
0.9729947756607252, 368s, 24ep, 3reduce

Everything the same except optimizer = adam, lr unset
0.9649277811923787, 138s, 42ep, 3reduced

Batch size: Custom_ReduceLROnPlateau, k=2, dropout=0.0, dataset=200000, lr=0.1, optimizer=SGDm w/o nev, patience=2,4

128: 0.9682698217578365, 122s, 22ep, 2reduced
to be submitted: 512: 0.9638521819299324, 92s, 29ep, 2reduced
1024: 0.9663106945298094, 88s, 29ep, 2reduced, 0.9643131530424094, 87s, 29ep, 1reduced
  
no custom:
128: 0.9625460971112477, 122s, 26ep, 3reduced
128: 0.9660802089735709, 119s, 24ep, 3reduced, 47.6min
512: 0.9683466502765826, 92s, 35ep, 2reduced, 53.6min
2048: 0.96269975414874, 85s, 33ep, 1reduced, 46.75min

Custom_ReduceLROnPlateau: batchsize=128 k=2, dropout=0.0, dataset=200000, lr=0.1, optimizer=SGDm w/o nev, patience=2,4

w/o: 0.9660802089735709, 119s, 24ep, 3reduced
w: 0.9672710510141365, 122s, 18ep 2reduced - seems like the model was pretrained already (forgot to create new model). No leh, its like that with custom
  
patience after reviving the model with lr factor=0.5: custom on
2,4: 0.9661954517516902, 122s, 26ep, 2reduced, 0.9651966810079902, 121s, 9ep, 0reduced
3,6: 0.9666564228641672, 124s, 26ep, 2reduced, 0.9668100799016595, 123s, 10ep, 0reduced - Died the same way
  
batchsize=128 k=2, dropout=0.0, dataset=200000, lr=0.1, optimizer=SGDm w/o nev, patience=2,4, w/o custome
revived with patience=2,6, factor=0.5: 0.9676936078672403, 123s, 30ep, 4reduced, 0.9668869084204057, 122s, 8ep, 0reduced (on custom)
revived with patience=2,4, factor=0.5: 0.9658497234173326, 123s, 34ep, 4reduced, 0.9660417947141979, 123s, 6ep, 0reduced
  
# Reviving the model yields no results
# First run of w/o custom can't seem to be replicated sadly
# custom reduces the number of ep

"""
Code for reviving the model:
If you rerun the model, would the LR start from the 2reduced or before it happened (when the model was saved), when the model was saved? Conduct a mini experiment with model 1 - it will continue from where the training stopped (after the 2reduced)

# model died at 0.0001 learn rate:
died_lr = float(K.get_value(model.optimizer.lr))
best_model_lr=died_lr*100 # (1/factor)^2
K.set_value(model.optimizer.lr, best_model_lr)

float(K.get_value(model.optimizer.lr))

# Change the factor of RLROP to 0.5 and rerun the model
"""

# batchsize: k=2, dropout=0.0, dataset=200000, lr=0.1, optimizer=SGDm w/o nev, patience=2,4

128: 0.9660802089735709, 119s, 24ep, 3reduced, 47.6min
512: 0.9683466502765826, 92s, 35ep, 2reduced, 53.6min
2048: 0.96269975414874, 85s, 33ep, 1reduced, 46.75min

# reduce patience and patience: k=2, dropout=0.0, dataset=100000, lr=0.1 optimizer=SGDm w/o nev

2,4: 0.9606253841425937, 61s, 34ep, 4reduced
3,6: 0.9584741856177013, 60s, 44ep, 2reduced

# dropout: k=2, dropout=0.0, dataset=100000, lr=0.1, optimizer=SGDm w/o nev, patience=4, reduce patience=2

0.0: 0.9606253841425937, 61s, 34ep, 4reduced
0.2: 0.9562077443146896, 63s, 27ep, 2reduced
0.4: 0.9534419176398279, 63s, 33ep, 2reduced

# Should increase the patience then test again. The model can't seem to adapt to the dropout then it decreases lr already
# Somehow the model is just 'not learning properly'

# optimizer: k=2, dropout=0.0, dataset=100000, patience=2

adam: 0.9435771358328211, 70s, 11.2ep
nadam: 0.9388444990780578, 73s, 11ep

# optimizer: k=2, dropout=0.0, dataset=100000, patience=4, reduce patience=2
adam: 0.958320528580209, 0.9576674861708666, 68s, 28ep, 2reduced
SGDm w/o nev: 0.9590503995082975, 61s, 43ep, 1reduced - takes 16 epoch to reach a starting val_loss of adam, but lr only reduce at 34ep
SGDm with nev: 0.9556699446834666, 62s, 38ep, 1reduced - takes 15 epoch to reach a starting val_loss of adam
  
# starting learn rate for SGDm w/o nev: k=2, dropout=0.0, dataset=100000, patience=4, reduce patience=2
0.01 0.9590503995082975, 61s, 43ep, 1reduced
0.1: 0.9606253841425937, 61s, 34ep, 4reduced - go read the log
# takes the same accuracy but reduces by 9ep

# Kaggle
# Batch size, dataset=100000, dropout=0.0, k=2, patience=2
32: 0.9384219422249539, 129s, 12ep, 15.8min
128: 0.9390749846342963, 70s, 9ep, 10.5min
256: 0.9474492931776275, 55s, 12ep, 11min
512: 0.9506760909649662, 49s, 19ep, 15.5min
1024: 0.9524047326367547, 46s, 20ep, 15.3min
2048: 0.9539028887523049, 45s, 20ep, 15min
4096: - not enough memory
    
# As batch_size increase, accuracy increases too
# from 256 to 1024, each increase brings 0.003
# time per epoch decreases decreasingly
# number of epochs is lowest at 128, and plateau at 512, at 20ep

256, 200000: 0.953480331899201, 110s, 15ep -val_loss: 0.1314 - val_acc: 0.9794
256, 300000: 0.9425706822372465, 128s, 13ep

# Compilation of all accuracies: k=2, dropout=0.0, dataset=100000, patience=2
100000: 0.9498309772587584, 70s, 18ep
2: 0.9463736939151813, 70s, 9ep
2: 0.9390749846342963, 70s, 9ep
0.0: 0.9407267977873387, 0.941879225568531, 70s, 7ep, 13ep

# Average: 0.9435771358328211, 70s, 11.2ep

# dropout rate: k=4, data=100000

0.0: 0.9473340503995082, 127s, 11ep
0.1: 0.9452212661339889, 133s, 11ep
0.2: 
  
# k=2:
0.0: 0.9407267977873387, 0.941879225568531, 70s, 7ep, 13ep
0.1: 0.9481023355869699, 70s, 17ep
0.2: 0.9330055316533498, 74s, 10ep
0.4: 0.940880454824831, 74s, 15ep
  
# It can be inferred that increasing k leads to a more reliable accuracy - not true

# Kaggle
# Patience, dataset=100000, dropout=0.0, k=2

2: 0.9390749846342963, 70s, 9ep
3; 0.9464505224339275, 70s, 22ep
4: 0.9490626920712969, 69s, 25ep

# Increasing patience increases ep and accuracy (by 0.003)

# Kaggle
# k value, dataset=100000, dropout=0.0

2: 0.9463736939151813, 70s, 9ep
4: 0.9420328826060234, 0.9388060848186847, 133s, 126s 9ep

# Amt of Data vs timing and accuracy, settings: k=2, dropout=0

73257: 0.9443377381684082, 50s, 11ep
100000: 0.9498309772587584, 70s, 18ep
150000: 0.9425322679778734, 104s, 8ep
200000: 0.939459127228027, 138s, 12ep
300000: 0.9492547633681623, 204s, 12ep
  
34s per 50k
>100k, leads to unnoticable difference - when k increases, hopefully test acc can match the val acc

Using adam optimiser, accuracy increased from 93.8 to 94.4, time per epoch dropped from 53s to 49s
