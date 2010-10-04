from hashlib import sha1

from Permission import AuthorizePermission, RevokePermission, PermitPermission
from Encoding import encode, decode
from Message import DelayPacket, DropPacket
from Message import Message
from Distribution import FullSyncDistribution, LastSyncDistribution, DirectDistribution, RelayDistribution
from Destination import MemberDestination, CommunityDestination, AddressDestination
from DispersyDatabase import DispersyDatabase

if __debug__:
    from Print import dprint

class ConversionBase(object):
    """
    A Conversion object is used to convert incoming packets to a
    different, often more recent, community version.  If also allows
    outgoing messages to be converted to a different, often older,
    community version.
    """ 
    def __init__(self, community, vid):
        """
        COMMUNITY instance that this conversion belongs to.
        VID is the conversion identifyer (on the wire version).
        """
        if __debug__: from Community import Community
        assert isinstance(community, Community)
        assert isinstance(vid, str)
        assert len(vid) == 5

        # the dispersy database
        self._dispersy_database = DispersyDatabase.get_instance()

        # the community that this conversion belongs to.
        self._community = community

        # the messages that this instance can handle, and that this
        # instance produces, is identified by _prefix.
        self._prefix = community.cid + vid

    @property
    def community(self):
        return self._community

    @property
    def vid(self):
        return self._prefix[20:25]

    @property
    def prefix(self):
        return self._prefix

    def decode_message(self, data):
        """
        DATA is a string, where the first 20 bytes indicate the CID,
        the next 5 byres the VID, and the rest forms a CID and VID
        dependent message payload.
        
        Returns a Message instance.
        """
        assert isinstance(data, str)
        assert len(data) >= 25
        assert data[:25] == self._prefix
        raise NotImplementedError()

    def encode_message(self, message):
        """
        Encode a Message instance into a binary string.
        """
        assert isinstance(message, Message)
        raise NotImplementedError()

    def decode_payload(self, privilege, stream, offset):
        """
        Decode community specific bytes from STREAM starting at
        OFFSET.  Returns the a (new-offset, payload) tuple.
        """
        assert isinstance(stream, str)
        assert isinstance(offset, (int, long))
        raise NotImplementedError()

    def encode_payload(self, message):
        """
        Encode the community specific message.permission.payload part
        into a binary string.
        """
        assert isinstance(message, Message)
        raise NotImplementedError()

class Conversion00001(ConversionBase):
    """
    On-The-Wire version 00001.

    USER-DESTINATION + DIRECT-MESSAGE
    =================================
    20 byte CID (community identifier)
     5 byte VID (on-the-wire protocol version)
    {
       signed_by: "public key, in PEM format"
       destination: {}
       distribution: {}
       permission: {}
    }
    20 byte signature of entire message (including CID and VID)
    """
    def __init__(self, community):
        ConversionBase.__init__(self, community, "00001")

        self._encode_destination_map = {MemberDestination.Implementation:self._encode_member_destination,
                                        CommunityDestination.Implementation:self._encode_community_destination,
                                        AddressDestination.Implementation:self._encode_address_destination}

        self._encode_distribution_map = {FullSyncDistribution.Implementation:self._encode_full_sync_distribution,
                                         LastSyncDistribution.Implementation:self._encode_last_sync_distribution,
                                         DirectDistribution.Implementation:self._encode_direct_distribution}

        self._encode_permission_map = {PermitPermission:self._encode_permit_permission,
                                       AuthorizePermission:self._encode_authorize_permission}

    @staticmethod
    def _decode_global_time(container, index):
        global_time = container.get(index)
        if not isinstance(global_time, (int, long)):
            raise DropPacket("Invalid global time type")
        if global_time <= 0:
            raise DropPacket("Invalid global time value {global_time}".format(global_time=global_time))
        return global_time

    @staticmethod
    def _decode_sequence_number(container, index):
        sequence_number = container.get(index)
        if not isinstance(sequence_number, (int, long)):
            raise DropPacket("Invalid sequence number type")
        if sequence_number <= 0:
            raise DropPacket("Invalid sequence number value {sequence_number}".format(sequence_number=sequence_number))
        return sequence_number
    
    def _decode_privilege(self, container, index):
        privilege = container.get(index)
        if not isinstance(privilege, unicode):
            raise DropPacket("Invalid privilege type")
        try:
            privilege = self._community.get_privilege(privilege)
        except KeyError:
            # the privilege is not known in this community.  delay
            # message processing for a while
            raise DropPacket("Invalid privilege")
        return privilege

    @staticmethod
    def _decode_permission(container, index):
        permission = container.get(index)
        if not isinstance(permission, unicode):
            raise DropPacket("Invalid authorized permission type")
        if permission == u"permit":
            permission = PermitPermission
        elif permission == u"authorize":
            permission = AuthorizePermission
        elif permission == u"revoke":
            permission = RevokePermission
        else:
            raise DropPacket("Invalid permission")
        return permission

    def _decode_member(self, container, index):
        public_key = container.get(index)
        if not isinstance(public_key, str):
            raise DropPacket("Invalid to-member type")
        try:
            member = self._community.get_member(public_key)
        except KeyError:
            # the user is not known in this community.  delay
            # message processing for a while
            raise DelayPacket("Unable to find to-member in community")
        return member

    def decode_message(self, data):
        """
        Convert version 00001 DATA into an internal data structure.
        """
        assert isinstance(data, str)
        assert len(data) >= 25
        assert data[:25] == self._prefix

        signature = data[-20:]
        container = decode(data, 25)
        if not isinstance(container, dict):
            raise DropPacket("Invalid container type")

        #
        # member (signer of the message)
        #
        public_key = container.get("signed_by")
        if not isinstance(public_key, str):
            raise DropPacket("Invalid public key type")
        try:
            member = self._community.get_member(public_key)
        except KeyError:
            # todo: delay + retrieve user public key
            raise DelayPacket("Unable to find member in community")

        if not member.verify_pair(data):
            raise DropPacket("Invalid signature")

        #
        # permission
        #
        d = container.get("permission")
        if not isinstance(d, dict):
            raise DropPacket("Invalid permission type")
        t = d.get("type")
        privilege = self._decode_privilege(d, "privilege_name")
        if t == "permit":
            _, payload = self.decode_payload(privilege, d.get("payload"), 0)
            permission = PermitPermission(privilege, payload)

        elif t == "authorize":
            permission = AuthorizePermission(privilege, self._decode_member(d, "to"), self._decode_permission(d, "permission_name"))

        else:
            raise NotImplementedError()

        #
        # destination
        #
        if isinstance(privilege.destination, MemberDestination):
            destination = privilege.destination.implement()

        elif isinstance(privilege.destination, CommunityDestination):
            destination = privilege.destination.implement()

        elif isinstance(privilege.destination, AddressDestination):
            destination = privilege.destination.implement(("", 0))

        else:
            raise DropPacket("Invalid destination")

        #
        # distribution
        #
        d = container.get("distribution")
        if not isinstance(d, dict):
            raise DropPacket("Invalid distribution type")
        if isinstance(privilege.distribution, FullSyncDistribution):
            global_time = self._decode_global_time(d, "global_time")
            sequence_number = self._decode_sequence_number(d, "sequence_number")
            distribution = privilege.distribution.implement(global_time, sequence_number)

        elif isinstance(privilege.distribution, LastSyncDistribution):
            global_time = self._decode_global_time(d, "global_time")
            distribution = privilege.distribution.implement(global_time)

        elif isinstance(privilege.distribution, DirectDistribution):
            global_time = self._decode_global_time(d, "global_time")
            distribution = privilege.distribution.implement(global_time)
            
        else:
            raise NotImplementedError()

        return Message(self._community, member, distribution, destination, permission)

    def _encode_not_implemented(self, _, __):
        raise NotImplementedError()

    def _encode_member_destination(self, container, _):
        container["debug-destination"] = {"debug-type":"member-destination"}

    def _encode_community_destination(self, container, _):
        container["debug-destination"] = {"debug-type":"community-destination"}

    def _encode_address_destination(self, container, _):
        container["debug-destination"] = {"debug-type":"address-destination"}

    def _encode_full_sync_distribution(self, container, message):
        container["distribution"] = {"global_time":message.distribution.global_time, "sequence_number":message.distribution.sequence_number}
        container["distribution"]["debug-type"] = "full-sync"

    def _encode_last_sync_distribution(self, container, message):
        container["distribution"] = {"global_time":message.distribution.global_time}
        container["distribution"]["debug-type"] = "last-sync"

    def _encode_direct_distribution(self, container, message):
        container["distribution"] = {"global_time":message.distribution.global_time}
        container["distribution"]["debug-type"] = "direct-message"

    def _encode_permit_permission(self, container, message):
        container["permission"] = {"type":"permit", "privilege_name":message.permission.privilege.name, "payload":self.encode_payload(message)}

    def _encode_authorize_permission(self, container, message):
        if issubclass(message.permission.permission, AuthorizePermission):
            permission_name = u"authorize"
        elif issubclass(message.permission.permission, RevokePermission):
            permission_name = u"revoke"
        elif issubclass(message.permission.permission, PermitPermission):
            permission_name = u"permit"
        else:
            raise NotImplementedError(message.permission.permission)

        container["permission"] = {"type":"authorize", "privilege_name":message.permission.privilege.name, "permission_name":permission_name, "to":message.permission.to.pem}

    def encode_message(self, message):
        if __debug__:
            from Member import PrivateMemberBase
        assert isinstance(message, Message)
        assert isinstance(message.signed_by, PrivateMemberBase)
        assert not message.signed_by.private_pem is None

        # stuff message in a container
        container = {"signed_by":message.signed_by.pem}
        self._encode_destination_map.get(type(message.destination), self._encode_not_implemented)(container, message)
        self._encode_distribution_map.get(type(message.distribution), self._encode_not_implemented)(container, message)
        self._encode_permission_map.get(type(message.permission), self._encode_not_implemented)(container, message)

        # encode and sign message
        return message.signed_by.generate_pair(self._prefix + encode(container))

class DefaultConversion(Conversion00001):
    """
    Conversion subclasses the current ConversionXXXXX class.
    """
    pass
