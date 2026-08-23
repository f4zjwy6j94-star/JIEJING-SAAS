# -*- coding: utf-8 -*-
"""Generated protobuf types for Tencent CLS UploadLog.

Source schema: the ``cls.proto`` published in Tencent Cloud's UploadLog API
documentation. Keep this module generated-only; application code belongs in
``monitoring.py``.
"""

from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder


_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\tcls.proto\x12\x03\x63ls"b\n\x03Log\x12\x10\n\x04time\x18\x01 \x02(\x03\x42\x02\x30\x01\x12"\n\x08\x63ontents\x18\x02 \x03(\x0b\x32\x10.cls.Log.Content\x1a%\n\x07\x43ontent\x12\x0b\n\x03key\x18\x01 \x02(\t\x12\r\n\x05value\x18\x02 \x02(\t"$\n\x06LogTag\x12\x0b\n\x03key\x18\x01 \x02(\t\x12\r\n\x05value\x18\x02 \x02(\t"w\n\x08LogGroup\x12\x16\n\x04logs\x18\x01 \x03(\x0b\x32\x08.cls.Log\x12\x13\n\x0b\x63ontextFlow\x18\x02 \x01(\t\x12\x10\n\x08\x66ilename\x18\x03 \x01(\t\x12\x0e\n\x06source\x18\x04 \x01(\t\x12\x1c\n\x07logTags\x18\x05 \x03(\x0b\x32\x0b.cls.LogTag"3\n\x0cLogGroupList\x12#\n\x0clogGroupList\x18\x01 \x03(\x0b\x32\r.cls.LogGroup'
)

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "jiejing_saas.cls_log_pb2", globals())
