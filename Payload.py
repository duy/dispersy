class Payload(object):
    @classmethod
    def get_static_type(cls):
        return {Authorize:u"authorize", Revoke:u"revoke", Permit:u"permit"}[cls]

    @property
    def name(self):
        raise NotImplementedError()

    @property
    def type(self):
        raise NotImplementedError()

    def __str__(self):
        return "<{0.__class__.__name__} {0.type}>".format(self)

class Authorize(Payload):
    def __init__(self, to, payload):
        """
        User TO is given permission to use PAYLOAD.

        TO: the member that is allowed to use PAYLOAD
        PAYLOAD: the kind of payload that TO is allowed to use
        """
        if __debug__:
            from Member import Member
            from Payload import Payload
            assert isinstance(to, Member)
            assert issubclass(payload, Payload)
        self._to = to
        self._payload = payload

    @property
    def type(self):
        return u"authorize"

    @property
    def to(self):
        return self._to

    @property
    def payload(self):
        return self._payload

class Revoke(Payload):
    def __init__(self, to, payload):
        """
        User TO is no longer allowed to use PAYLOAD.
        """
        if __debug__:
            from Member import Member
            from Payload import Payload
            assert isinstance(to, Member)
            assert issubclass(payload, Payload)
        self._to = to
        self._payload = payload

    @property
    def type(self):
        return u"revoke"

    @property
    def to(self):
        return self._to

    @property
    def payload(self):
        return self._payload

class Permit(Payload):
    @property
    def type(self):
        return u"permit"

class MissingSequencePayload(Permit):
    def __init__(self, member, message, missing_low, missing_high):
        """
        We are missing messages of type MESSAGE signed by USER.  We
        are missing sequence numbers >= missing_low to <=
        missing_high.
        """
        if __debug__:
            from Member import Member
            from Message import Message
        assert isinstance(member, Member)
        assert isinstance(message, Message)
        assert isinstance(missing_low, (int, long))
        assert isinstance(missing_high, (int, long))
        assert 0 < missing_low <= missing_high
        self._member = member
        self._message = message
        self._missing_low = missing_low
        self._missing_high = missing_high

    @property
    def member(self):
        return self._member

    @property
    def message(self):
        return self._message

    @property
    def missing_low(self):
        return self._missing_low

    @property
    def missing_high(self):
        return self._missing_high

class SyncPayload(Permit):
    def __init__(self, global_time, bloom_filter):
        if __debug__:
            from Bloomfilter import BloomFilter
        assert isinstance(global_time, (int, long))
        assert isinstance(bloom_filter, BloomFilter)
        self._global_time = global_time
        self._bloom_filter = bloom_filter

    @property
    def global_time(self):
        return self._global_time

    @property
    def bloom_filter(self):
        return self._bloom_filter
