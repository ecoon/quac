'''Glue classes to let Python code use the QUACreduce protocol. Subclass Job,
   plus mixins as needed, and then implement the abstract classes.

   Many of these methods refer to *key/value pairs*; the key is a non-None
   string not containing any of the characters prohibited by the QUACreduce
   protocol (or an object that produces this when ``str()`` is called on it),
   and the value is any Python object that can be pickled or None. Similarly,
   *items* have the same constraints as values.

   To invoke a mapper or reducer:

     1. Set up standard input and/or standard output pipes as appropriate.
     2. Import the module.
     3. Create a Job object, passing a parameter dictionary if desired.
     4. Call :meth:`map_stdinout()` or :meth:`reduce_stdinout()`.

   Note that this is awkward to do from the command line. If that becomes a
   typical use case, we can introduce a wrapper script.

   Mappers and reducers are *not* thread-safe. Each should run in its own
   process.

   .. note:: Map & reduce input and map output have no special buffer setup
      because they are expected to be connected to standard input and standard
      output, respectively. However, reduce output is expected to go to disk,
      so we set a large buffer in order to prepare for filesystems that use
      large blocks (e.g., Panasas and some RAID).

   .. note:: Subclasses must inherit from mixins *before* :class:`Job` to
      avoid "cannot create a consistent method resolution". It's possible the
      mixins aren't implemented correctly; patches welcome. Or, they're not
      really mixins (inheriting from :class:`Job` isn't actually required)?'''

# Copyright (c) Los Alamos National Security, LLC, and others.


from abc import ABCMeta, abstractmethod
import base64
import pickle as pickle
import io
import itertools
import operator
import sys

import testable
import tsv_glue
import u


# We use a relatively large output buffer size; see also OUTPUT_BUFSIZE in
# hashsplit.c.)
OUTPUT_BUFSIZE = 4194304


### Helper functions ###

def decode(bytes_):
   return pickle.loads(base64.b64decode(bytes_))

def encode(value):
   return base64.b64encode(pickle.dumps(value, -1))



### Classes ###

class Job(object, metaclass=ABCMeta):

   def __init__(self, params=None):
      # Note: Intepreting params involves a strange hack, because the user can
      # either pass a string-encoded dictionary or an arbitrary data structure
      # that's been encode()ed (see above). By a quirk of the quacreduce
      # transport scheme, the latter will arrive here as a single-element
      # dictionary with the encoded string as the key and an empty string as
      # the value (this works in part because base64 does not use the colon or
      # space characters). Therefore, if we get a dictionary that looks like
      # that, assume the real payload is in the (single) key.
      if (params is None):
         self.params = None
      else:
         if (len(params) == 1 and list(params.values())[0] == ''):
            self.params = decode(list(params.keys())[0])
         else:
            self.params = params
      self.rid = None
      # Yes, you can quac() instead of map() ...
      self.quac = self.map

   ## Instance properties

   @property
   def outdir(self):
      # FIXME: assumes cwd is jobdir... is that reasonable?
      return ('out')

   @property
   def reduce_output_filename(self):
      return ('%s/%d' % (self.outdir, self.rid))

   ## Instance methods

   def cleanup(self):
      # We didn't have to flush() when map_stdinout() was a class method; not
      # sure why we do now when it's an instance method.
      self.outfp.flush()

   @abstractmethod
   def map(self, item):
      '''FIXME generator yields key/value pairs'''

   def map_init(self):
      'Called before mapping begins.'

   def map_inputs(self):
      '''Generator which reads map input items from the mapper input (i.e.,
         the open file ``self.infp``) and yields them as Python objects. The
         default implementation assumes that :attr:`infp` is an iterator and
         yields elements of that iterator.'''
      for i in self.infp:
         yield i

   def map_open_input(self):
      self.infp = io.open(sys.stdin.fileno(), 'rb')

   def map_open_output(self):
      self.outfp = io.open(sys.stdout.fileno(), 'wb')

   def map_stdinout(self):
      '''Connect myself to input and output and run my mapper.'''
      #p = u.Profiler()
      self.map_open_input()
      self.map_open_output()
      self.map_init()
      for i in self.map_inputs():
         for kv in self.map(i):
            self.map_write(*kv)
      self.cleanup()
      #p.stop('map.prof')

   def map_write(self, key, value):
      '''Write one key/value pair to the mapper output.'''
      self.outfp.write(str(key).encode('utf8'))
      self.outfp.write(b'\t')
      self.outfp.write(encode(value))
      self.outfp.write(b'\n')

   @abstractmethod
   def reduce(self, key, values):
      '''Generator which yields zero or more reduced items based upon the key
         and an iterator of one or more corresponding values.'''
      pass

   def reduce_init(self):
      'Called before reducing begins.'
      pass

   def reduce_inputs(self):
      '''Generator which yields, for each key in the reducer input, a pair
         containing that key and an iterator of one or more corresponding
         values.'''
      for grp in itertools.groupby((l.partition(b'\t') for l in self.infp),
                                   key=operator.itemgetter(0)):
         key = grp[0].decode('utf8')
         values = (decode(i[2]) for i in grp[1])
         yield (key, values)

   def reduce_open_input(self):
      self.infp = io.open(sys.stdin.fileno(), 'rb')

   def reduce_open_output(self):
      self.outfp = io.open(self.reduce_output_filename, 'wb',
                           buffering=OUTPUT_BUFSIZE)

   def reduce_open_output_utf8(self):
      self.outfp = io.open(self.reduce_output_filename, 'wt',
                           encoding='utf8', buffering=OUTPUT_BUFSIZE)

   def reduce_stdinout(self, rid):
      '''Connect myself to input and output, and run my reducer.'''
      #p = u.Profiler()
      self.rid = rid
      self.reduce_open_input()
      self.reduce_open_output()
      self.reduce_init()
      for kvals in self.reduce_inputs():
         for item in self.reduce(*kvals):
            self.reduce_write(item)
      self.cleanup()
      #p.stop('reduce.prof')

   @abstractmethod
   def reduce_write(self, item):
      '''Write one Python object, ``item``, to the reduce output stream (the
         open file ``self.outfp``). Often, this will be implemented by a mixin
         (e.g. :class:`Line_Output`).'''
      pass


class Line_Input_Job(Job):

   '''Mixin for line-oriented Unicode plain text map input;
      :meth:`map_inputs()` yields Unicode objects.'''

   def map_open_input(self):
      self.infp = io.open(sys.stdin.fileno(), 'rt', encoding='utf8')


class Line_Output_Job(Job):

   'Mixin for line-oriented Unicode plain text reduce output.'

   def reduce_open_output(self):
      self.reduce_open_output_utf8()

   def reduce_write(self, item):
      'Items to be unicode objects with no trailing newline.'
      assert (isinstance(item, str))
      self.outfp.write(item)
      self.outfp.write('\n')


class KV_Pickle_Seq_Input_Job(Job):

   '''Mixin for input that is a sequence of Python objects. :meth:`map` must
      accept (key, value) tuples.

      The input stream is a sequence of lines with the following structure:
      the stringified key, a tab character, a pickled and base64-encoded
      version of the value, and a newline. (This is a *sequence* of pickles,
      not a pickle containing a sequence.) Note that keys are not necessarily
      unique.'''

   def map_inputs(self):
      for l in self.infp:
         (key, _, value) = l.partition(b'\t')
         key = key.decode('utf8')
         value = decode(value)  # base64 ignores trailing newline
         yield (key, value)


class KV_Pickle_Seq_Output_Job(Job):

   '''Mixin for output that is a sequence of Python objects. :meth:`reduce`
      must yield (key, value) tuples. See :class:`KV_Pickle_Seq_Input_Job` for
      the output stream format.'''

   def reduce_write(self, item):
      assert (len(item) == 2)
      self.outfp.write(str(item[0]).encode('utf8'))
      self.outfp.write(b'\t')
      self.outfp.write(encode(item[1]))
      self.outfp.write(b'\n')

class Test_Job(Job):
   'Job with dummy implementations of all the abstract methods, for testing.'
   def map(self, item): pass
   def map_inputs(self): pass
   def reduce(self, key, values): pass
   def reduce_write(self, item): pass


class TSV_Input_Job(Job):

   '''Mixin for TSV UTF-8 text input. Uses our dirt-simple TSV parser (split
      on tabs, nothing more). :meth:`map_inputs()` yields lists of Unicode
      strings.'''

   def map_open_input(self):
      self.infp = tsv_glue.Reader(sys.stdin.fileno())


class TSV_Internal_Job(Job):

   '''Values transferred from mappers to reducers are iterables. They are
      "encoded" by simple tab separation. No checks for internal tabs or
      newlines are performed, and anything that is not a string object needs
      to be manually dealt with (keys are still Unicode).'''

   def map_write(self, key, value):
      self.outfp.write(key)
      for v in value:
         self.outfp.write(b'\t')
         self.outfp.write(v.encode('utf8'))
      self.outfp.write(b'\n')

   def reduce_inputs(self):
      for (key, values) in itertools.groupby((l.split(b'\t') for l in self.infp),
                                             key=operator.itemgetter(0)):
         try:
            key = key.decode('utf8')
            # Skip first item in each iterator within values (it's the key
            # again). We use a generator and islice() to remain lazy.
            values = (itertools.islice(i, 1, None) for i in values)
            yield (key, values)
         except UnicodeDecodeError:
            # ignore Unicode problems, as they represent broken URLs
            continue


class TSV_Output_Job(Job):

   '''Mixin for TSV UTF-8 text output. :meth:`reduce_write()` expects a
      sequence of stringifiable objects.'''

   def reduce_open_output(self):
      assert False, 'unimplemented'

   def reduce_write(self, item):
      self.outfp.writerow(item)


testable.register(r'''

# Test data passing from mapper to reducer.
>>> import io
>>> buf = io.BytesIO()
>>> job = Test_Job()
>>> job.outfp = buf
>>> for kv in [(1, -1), (2, -2), (2, -3), (3, -4), (3, -5), (3, -6)]:
...    job.map_write(*kv)
>>> buf.getvalue()
b'1\tgASVBgAAAAAAAABK/////y4=\n2\tgASVBgAAAAAAAABK/v///y4=\n2\tgASVBgAAAAAAAABK/f///y4=\n3\tgASVBgAAAAAAAABK/P///y4=\n3\tgASVBgAAAAAAAABK+////y4=\n3\tgASVBgAAAAAAAABK+v///y4=\n'
>>> buf.seek(0)
0
>>> job.infp = buf
>>> [(k, list(v)) for (k, v) in job.reduce_inputs()]
[('1', [-1]), ('2', [-2, -3]), ('3', [-4, -5, -6])]

''')
