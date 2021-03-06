# -*- coding: utf-8 -*-

'''Hash functions. This module is here so that we can have hash algorithms
   with identical results in Python, C, and perhaps other places. The primary
   documentation is here.

   Unless otherwise specified, these algorithms operate on bytes objects. They
   also accept str objects, which are converted to bytes by encoding in UTF-8.

   None of the Python implementations are optimized for speed.

   Run the interactive test for visualizations of hash quality.'''

# Copyright (c) Los Alamos National Security, LLC, and others.

# Implementation note: In principle, we could implement the algorithms once,
# in C, and then access that implementation from Python (e.g., using ctypes).
# However, we don't have much code yet, so it's less work to simply have a
# duplicate implementation. (We would need tests on both sides anyway.)

# If you edit this file, make sure tests match hashsplit.c.



import testable
import u


def byteify(byteme):
   '''Return a byte string representation of byteme. E.g.:

       >>> from binascii import hexlify
       >>> hexlify(byteify('abc'))
       b'616263'
       >>> hexlify(byteify(u'私の名前'))
       b'e7a781e381aee5908de5898d'
       >>> byteify(8675309)
       Traceback (most recent call last):
       ValueError: cannot convert <class 'int'> to byte string'''
   if (isinstance(byteme, bytes)):
      return byteme
   elif (isinstance(byteme, str)):
      return byteme.encode('utf8')
   else:
      raise ValueError('cannot convert %s to byte string' % (type(byteme)))

def consecutive(x, bin_ct, min_, max_):
   '''Hash integers into consecutive bins. Given a range of integers from min_
      to max_ inclusive, divide it into bin_ct bins of consecutive integers
      numbered 0 to bin_ct-1. Return the bin index containing x. E.g.:

      >>> [consecutive(i, 3, 11, 24) for i in range(11, 25)]
      [0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 2]
      >>> [consecutive(i, 3, 0, 2) for i in range(3)]
      [0, 1, 2]
      >>> [consecutive(i, 3, 0, 3) for i in range(4)]
      [0, 1, 2, 2]
      >>> [consecutive(i, 3, 0, 4) for i in range(5)]
      [0, 0, 1, 2, 2]'''
   per_bin = (max_ - min_) / bin_ct
   return int(min((x - min_) / per_bin, bin_ct - 1))

def djb2(bytes_):
   '''Bernstein's DJB2 hash (http://www.cse.yorku.ca/~oz/hash.html), XOR
       variant. For example:

       >>> djb2('b')
       177607
       >>> djb2('b') % 240
       7
       >>> djb2('nullvaluenotab') % 240
       19
       >>> djb2(u'私の名前は中野です') % 240
       19

       Warning: This algorithm has poor performance for our applications.'''
   bytes_ = byteify(bytes_)
   hash_ = 5381
   for b in bytes_:
      # mod operation simulates 32-bit unsigned int overflow
      hash_ = ((hash_ * 33) % 2**32) ^ b
   return hash_

def fnv1a_32(bytes_):
   '''Bernstein's DJB2 hash (http://www.cse.yorku.ca/~oz/hash.html), XOR
       variant. For example:

       >>> fnv1a_32('b')
       3876335077
       >>> fnv1a_32('b') % 240
       37
       >>> fnv1a_32('nullvaluenotab') % 240
       145
       >>> fnv1a_32(u'私の名前は中野です') % 240
       5'''
   bytes_ = byteify(bytes_)
   hash_ = 2166136261
   for b in bytes_:
      hash_ = hash_ ^ b
      hash_ = (hash_ * 16777619) % 2**32
   return hash_

def of(bytes_):
   '''Main entry point for the module. This invokes the current "best" hash
      algorithm.'''
   return fnv1a_32(bytes_)


testable.register('')

def test_interactive():
   '''Compute the hashes of some problematic data of ours (names of Wikimedia
      pageview files) and plot the results of several different hash sizes.
      The ideal plot is a horizontal line.'''
   import matplotlib.pyplot as plt
   inputs = open(u.quacbase
                 + '/tests/standalone/wp-access/ls-R.fulldata').readlines()
   for hashmod in [2**i for i in range(1, 13)] + [240, 251]:
      buckets = { i: 0 for i in range(hashmod) }
      for i in inputs:
         buckets[of(i) % hashmod] += 1
      plt.plot(list(buckets.values()))
      plt.plot(sorted(buckets.values()))
      plt.axis([(hashmod - 1) * -0.02, (hashmod - 1) * 1.02,
                0, max(buckets.values()) * 1.02])
      plt.title('hashmod = %d' % (hashmod))
      plt.show()
