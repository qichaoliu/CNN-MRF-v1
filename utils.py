# -*- coding: utf-8 -*-
"""
Created on Sat Feb 18 16:21:13 2017
@author: Xiangyong Cao
This code is modified based on https://github.com/KGPML/Hyperspectral
"""


import tensorflow as tf
import numpy as np
import scipy.io as io
from pygco import cut_simple, cut_simple_vh
from sklearn.metrics import accuracy_score
import matplotlib.pyplot as plt
import spectral as spy
import cv2
from skimage.util import pad
from collections import Counter

patch_size = 9   # can be tuned

class DataSet(object):

    def __init__(self, images, labels, dtype=tf.float32):

        """Construct a DataSet.

        FIXME: fake_data options

        one_hot arg is used only if fake_data is true.  `dtype` can be either
        `uint8` to leave the input as `[0, 255]`, or `float32` to rescale into
        `[0, 1]`.
        """
        images = np.transpose(images,(0,2,3,1))
        labels = np.transpose(labels)
        
        
        dtype = tf.as_dtype(dtype).base_dtype
        if dtype not in (tf.uint8, tf.float32):
            raise TypeError('Invalid image dtype %r, expected uint8 or float32' %
                          dtype)


        assert images.shape[0] == labels.shape[0], (
            'images.shape: %s labels.shape: %s' % (images.shape, labels.shape))
        self._num_examples = images.shape[0]

        images = images.reshape(images.shape[0],images.shape[1] * images.shape[2] * images.shape[3])

            
        self._images = images
        self._labels = labels
        self._epochs_completed = 0
        self._index_in_epoch = 0

    @property
    def images(self):
        return self._images

    @property
    def labels(self):
        return self._labels

    @property
    def num_examples(self):
        return self._num_examples

    @property
    def epochs_completed(self):
        return self._epochs_completed

    def next_batch(self, batch_size):
        """Return the next `batch_size` examples from this data set."""
        start = self._index_in_epoch
        self._index_in_epoch += batch_size
        if self._index_in_epoch > self._num_examples:
            # Finished epoch
            self._epochs_completed += 1
            # Shuffle the data
            perm = np.arange(self._num_examples)
            np.random.shuffle(perm)
            self._images = self._images[perm]
            self._labels = self._labels[perm]
            # Start next epoch
            start = 0
            self._index_in_epoch = batch_size
            assert batch_size <= self._num_examples
        end = self._index_in_epoch
        return self._images[start:end], np.reshape(self._labels[start:end],len(self._labels[start:end]))



def read_data_sets(directory,value, dtype=tf.float32):

    images = io.loadmat(directory)[value+'_patch']
    labels = io.loadmat(directory)[value+'_labels']

    data_sets = DataSet(images, labels, dtype=dtype)

    return data_sets


def convertToOneHot(vector, num_classes=None):
    """
    Converts an input 1-D vector of integers into an output
    2-D array of one-hot vectors, where an i'th input value
    of j will set a '1' in the i'th row, j'th column of the
    output array.

    Example:
        v = np.array((1, 0, 4))
        one_hot_v = convertToOneHot(v)
        print one_hot_v

        [[0 1 0 0 0]
         [1 0 0 0 0]
         [0 0 0 0 1]]
    """

    assert isinstance(vector, np.ndarray)
    assert len(vector) > 0

    if num_classes is None:
        num_classes = np.max(vector)+1
    else:
        assert num_classes > 0
        assert num_classes >= np.max(vector)

    result = np.zeros(shape=(len(vector), num_classes))
    result[np.arange(len(vector)), vector] = 1
    return result.astype(int)

def draw(GT_Label,ES_Label):
    fig = plt.figure(figsize=(12,6))
    
    p = plt.subplot(1,2,1)
    v = spy.imshow(classes=GT_Label,fignum=fig.number)
    p.set_title('Ground Truth')
    p.set_xticklabels([])
    p.set_yticklabels([])

    p = plt.subplot(1,2,2)
    v = spy.imshow(classes=ES_Label * (GT_Label!=0),fignum=fig.number)
    p.set_title('CLassification Map')
    p.set_xticklabels([])
    p.set_yticklabels([])
    
def unaries_reshape(unaries,height,width,num_classes):
    una = []
    for i in range(num_classes):
        temp = unaries[:,i].reshape(height,width).transpose(1,0)
        una.append(temp)
    return np.dstack(una).copy("C")


def Post_Processing(prob_map,height,width,num_classes,y_test,test_indexes):
#    unaries = (prob_map+1e-7).astype(np.int32)
    unaries = (-5 * np.log(prob_map+1e-7)).astype(np.int32)
    una = unaries_reshape(unaries,width,height,num_classes)
    one_d_topology = (np.ones(num_classes)-np.eye(num_classes)).astype(np.int32).copy("C")
    Seg_Label = cut_simple(una, 2 * one_d_topology)
    Seg_Label = Seg_Label + 1
    seg_Label = Seg_Label.transpose().flatten()
    seg_accuracy = accuracy_score(y_test,seg_Label[test_indexes])
    return Seg_Label, seg_Label, seg_accuracy
 
def Median_filter(prob_map,height,width,y_test,test_indexes):
    Cla_Label = np.argmax(prob_map,1) + 1
    Cla_Label = Cla_Label.reshape(height,width).transpose(1,0)
    Cla_Label = Cla_Label.astype(np.uint8)
    Median_Label = cv2.medianBlur(Cla_Label,3)
    median_Label = Median_Label.transpose().flatten()
    median_accuracy = accuracy_score(y_test,median_Label[test_indexes].flatten())
    return Median_Label, median_Label, median_accuracy 

def Patch(Label_Padding,height_index,width_index,ksize):
    """ function to extract patches from the orignal data """
    height_slice = slice(height_index, height_index + ksize)
    width_slice = slice(width_index, width_index + ksize)
    patch = Label_Padding[height_slice, width_slice]
    return np.array(patch) 

def mv_calculate(patch):
    patch_vec = list(patch.flatten())
    patch_vec = [i for i in patch_vec if i>0]
    mv_value = Counter(patch_vec).most_common(1)[0][0]
    return mv_value
    
def Majority_voting(Label,ksize):
    ## padding the data beforehand
    Height, Width= Label.shape[0], Label.shape[1]
    Label_Padding = pad(Label,int((ksize-1)/2),'constant')
    MV_Label = np.zeros((Height,Width))
    for j in range(0,Width):
        for i in range(0,Height):
            curr_patch = Patch(Label_Padding,i,j,ksize)
            MV_Label[i,j] = mv_calculate(curr_patch)            
    return MV_Label
    

    