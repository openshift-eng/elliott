from __future__ import absolute_import, print_function, unicode_literals
from future.utils import as_native_str


class ModelException(Exception):

    def __init__(self, msg, result=None, **kwargs):
        super(self.__class__, self).__init__(msg)
        self.msg = msg
        self.result = result
        self.kwargs = kwargs

    def attributes(self):
        return dict(self.kwargs)

    def as_dict(self):
        d = dict(self.kwargs)
        d["msg"] = self.msg
        if self.result is not None:
            d["result"] = self.result
        return d

    @as_native_str()
    def __str__(self):
        if self.result is None:
            return self.msg
        return "[" + self.msg + "]\n" + repr(self.result)


class MissingModel(dict):

    def __init__(self):
        super(self.__class__, self).__init__()
        pass

    def __getattr__(self, attr):
        return self

    def __setattr__(self, key, value):
        raise ModelException("Invalid attempt to set key(%s) in missing branch of model" % key)

    def __delattr__(self, key):
        raise ModelException("Invalid attempt to delete key(%s) in missing branch of model" % key)

    def __getitem__(self, attr):
        return self

    def __setitem__(self, key, value):
        raise ModelException("Invalid attempt to set key(%s) in missing branch of model" % key)

    def __delitem__(self, key):
        raise ModelException("Invalid attempt to delete key(%s) in missing branch of model" % key)

    @as_native_str()
    def __str__(self):
        return "(MissingModel)"

    @as_native_str()
    def __repr__(self):
        return "(MissingModel)"


# Singleton which indicates if any model attribute was not defined
Missing = MissingModel()


def to_model_or_val(v):
    if isinstance(v, list):
        return ListModel(v)
    elif isinstance(v, dict):
        return Model(v)
    else:
        return v


class ListModel(list):

    def __init__(self, list_to_model):
        super(self.__class__, self).__init__()
        if list_to_model is not None:
            self.extend(list_to_model)

    def __setitem__(self, key, value):
        super(self.__class__, self).__setitem__(key, value)

    def __delitem__(self, key):
        super(self.__class__, self).__delitem__(key)

    def __getitem__(self, index):
        if super(self.__class__, self).__len__() > index:
            v = super(self.__class__, self).__getitem__(index)
            if isinstance(v, Model):
                return v
            v = to_model_or_val(v)
            self.__setitem__(index, v)
            return v

        # Otherwise, trigger out of bounds exception
        return super(self.__class__, self).__getitem__(index)

    def __iter__(self):
        for i in range(0, super(self.__class__, self).__len__()):
            yield self[i]

    # Converts the model to a raw list
    def primitive(self):
        lst = []
        for e in self:
            lst.append(e)
        return lst


class Model(dict):

    def __init__(self, dict_to_model=None):
        super(Model, self).__init__()
        if dict_to_model is not None:
            for k, v in dict_to_model.items():
                self[k] = v

    def __getattr__(self, attr):
        if super(Model, self).__contains__(attr):
            v = super(self.__class__, self).get(attr)
            if isinstance(v, Model):
                return v
            v = to_model_or_val(v)
            self.__setattr__(attr, v)
            return v
        else:
            return Missing

    def __setattr__(self, key, value):
        self.__setitem__(key, value)

    def __getitem__(self, key):
        return self.__getattr__(key)

    def __setitem__(self, key, value):
        super(Model, self).__setitem__(key, value)

    def __delitem__(self, key):
        super(Model, self).__delitem__(key)

    def primitive(self):
        """ Recursively turn Model into dicts. """
        d = {}
        for k, v in self.items():
            if isinstance(v, Model) or isinstance(v, ListModel):
                v = v.primitive()
            d[k] = v
        return d
