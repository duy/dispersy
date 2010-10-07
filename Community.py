from hashlib import sha1

from Bloomfilter import BloomFilter
from Timeline import Timeline
from Privilege import PublicPrivilege
from Permission import AuthorizePermission, RevokePermission, PermitPermission
from Conversion import DefaultConversion
from Crypto import rsa_generate_key, rsa_to_public_pem, rsa_to_private_pem
from Dispersy import Dispersy
from DispersyDatabase import DispersyDatabase
from Member import MasterMember, MyMember, Member
from Message import Message, DelayMessageByProof
from Destination import CommunityDestination, AddressDestination
from Distribution import FullSyncDistribution, LastSyncDistribution, DirectDistribution
from Encoding import encode

if __debug__:
    from Print import dprint

class Community(object):
    """
    The Community module manages the participation and the reconstruction
    of the current state of a distributed community.
    """
    @classmethod
    def create_community(cls, my_member, *args, **kargs):
        """
        Create a new CLS community owned by MY_MEMBER.

        CLS is a Community subclass.  A new instance of this is returned.
        MY_MEMBER is a Member that will be granted all Permissions for PRIVILEGES.
        *ARGS are passed along to __init__
        **KARGS are passed along to __init__
        """
        if __debug__:
            from Privilege import PrivilegeBase
        assert isinstance(my_member, MyMember)

        # master key and community id
        rsa = rsa_generate_key(512)
        public_pem = rsa_to_public_pem(rsa)
        private_pem = rsa_to_private_pem(rsa)
        cid = sha1(public_pem).digest()

        database = DispersyDatabase.get_instance()
        with database as execute:
            execute(u"INSERT INTO community(user, cid, master_pem) VALUES(?, ?, ?)", (my_member.database_id, buffer(cid), buffer(public_pem)))
            database_id = database.last_insert_rowid
            execute(u"INSERT INTO user(mid, pem) VALUES(?, ?)", (buffer(cid), buffer(public_pem)))
            execute(u"INSERT INTO key(public_pem, private_pem) VALUES(?, ?)", (buffer(public_pem), buffer(private_pem)))
            execute(u"INSERT INTO routing(community, host, port, incoming_time, outgoing_time) SELECT ?, host, port, incoming_time, outgoing_time FROM routing WHERE community = 0", (database_id,))

        # new community instance
        community = cls(cid, *args, **kargs)

        # authorize MY_MEMBER for each privilege
        permission_pairs = []
        for privilege in community.get_privileges():
            if not isinstance(privilege, PublicPrivilege.Implementation):
                for permission in (AuthorizePermission, RevokePermission, PermitPermission):
                    permission_pairs.append((privilege, permission))
        if permission_pairs:
            community.authorize(my_member, permission_pairs, True)

        return community

    @staticmethod
    def join_community(cls, master_pem, my_member, *args, **kargs):
        """
        Joins a discovered community.  Returns a Community subclass
        instance.
        """
        assert isinstance(master_pem, str)
        assert isinstance(my_member, MyMember)
        cid = sha1(master_pem).digest()
        database = DispersyDatabase.get_instance()
        database.execute(u"INSERT INTO community(user, cid, master_pem) VALUES(?, ?, ?)",
                         (my_member.database_id, buffer(cid), master_pem))

        # new community instance
        return cls(cid, *args, **kargs)

    @staticmethod
    def load_communities():
        """
        Load existing communities.  Returns a list with zero or more
        Community subclass instances.
        """
        raise NotImplementedError()

    def __init__(self, cid):
        """
        CID is the community identifier.
        """
        assert isinstance(cid, str)
        assert len(cid) == 20

        # community identifier
        self._cid = cid

        # incoming message map
        self._incoming_message_map = {PermitPermission:self.on_message,
                                      AuthorizePermission:self.on_authorize_message,
                                      RevokePermission:self.on_revoke_message}

        # dispersy
        self._dispersy_database = DispersyDatabase.get_instance()

        try:
            community_id, master_pem, user_pem = self._dispersy_database.execute(u"""
            SELECT community.id, community.master_pem, user.pem
            FROM community
            LEFT JOIN user ON community.user = user.id
            WHERE cid == ?
            LIMIT 1""", (buffer(self._cid),)).next()

            # the database returns <buffer> types, we use the binary
            # <str> type internally
            master_pem = str(master_pem)
            user_pem = str(user_pem)
           
        except StopIteration:
            raise ValueError(u"Community not found in database")
        self._database_id = community_id
        self._my_member = MyMember.get_instance(user_pem)
        self._master_member = MasterMember.get_instance(master_pem)

        # implement the privileges
        self._privileges = {}
        for meta in self.get_dispersy_meta_privileges():
            assert meta.name not in self._privileges
            self._privileges[meta.name] = meta.implement(self)
        assert u"dispersy-sync" in self._privileges, "The 'dispersy-sync' Privilege has to be supplied"
        for meta in self.get_meta_privileges():
            assert meta.name not in self._privileges
            self._privileges[meta.name] = meta.implement(self)

        # the list with bloom filters.  the list will grow as the
        # global time increases.  The 1st bloom filter will contain
        # all stored messages from global time 1 to stepping.  The 2nd
        # from stepping to 2*stepping, etc.
        self._bloom_filter_stepping = 100
        self._bloom_filters = [BloomFilter(100, 0.01)]

        # dictionary containing available conversions.  currently only
        # contains one conversion.
        default_conversion = DefaultConversion(self)
        self._conversions = {None:default_conversion, default_conversion.prefix:default_conversion}

        # dictionary with in-memory community members
        # todo: load from database
        self._members = {self._master_member.pem:self._master_member,
                         self._my_member.pem:self._my_member}

        # initial timeline containing all known privileges
        self._timeline = Timeline(self)

        self._dispersy = Dispersy.get_instance()
        self._dispersy.add_community(self)

    def get_bloom_filter(self, global_time):
        """
        Returns the bloom-filter associated to global-time
        """
        index = global_time / self._bloom_filter_stepping
        while len(self._bloom_filters) <= index:
            self._bloom_filters.append(BloomFilter(100, 0.01))
        return self._bloom_filters[index]

    def get_current_bloom_filter(self):
        """
        Returns (global-time, bloom-filter)
        """
        index = len(self._bloom_filters) - 1
        return index * self._bloom_filter_stepping + 1, self._bloom_filters[index]

    @property
    def cid(self):
        return self._cid

    @property
    def database_id(self):
        return self._database_id

    @property
    def master_member(self):
        """
        Returns the community MasterMember instance.
        """
        return self._master_member

    @property
    def my_member(self):
        """
        Returns our own MyMember instance.
        """
        return self._my_member
        
    def get_member(self, public_key):
        """
        Returns a Member instance associated with PUBLIC_KEY.
        """
        assert isinstance(public_key, str)
        if not public_key in self._members:
            self._members[public_key] = Member.get_instance(public_key)
        return self._members[public_key]

    def get_conversion(self, prefix=None):
        return self._conversions[prefix]

    def add_conversion(self, conversion, default=False):
        if default:
            self._conversions[None] = conversion
        self._conversions[conversion.prefix] = conversion

    def authorize(self, member, permission_pairs, sign_with_master=False, update_locally=True, store_and_forward=True):
        """
        Grant MEMBER the PERMISSION_PAIRS.

        MEMBER is the Member who will obtain the new permissions.
        PERMISSIONS_PAIRS is a list containing (Privilege, Permission) tuples.
         where Privilege is the Privilege that the Member will obtain and
         where Permission is the Permission for that Privilege that the Member will obtain.
        SIGN_WITH_MASTER when True the MasterMember is used to sign the authorize message.
        """
        if __debug__:
            from Privilege import PrivilegeBase
            from Permission import PermissionBase
        assert isinstance(member, Member)
        assert isinstance(permission_pairs, (tuple, list))
        assert not filter(lambda x: not isinstance(x, tuple), permission_pairs)
        assert not filter(lambda x: not len(x) == 2, permission_pairs)
        assert not filter(lambda x: not isinstance(x[0], PrivilegeBase.Implementation), permission_pairs)
        assert not filter(lambda x: not issubclass(x[1], PermissionBase), permission_pairs)
        assert isinstance(sign_with_master, bool)
        assert isinstance(update_locally, bool)
        assert isinstance(store_and_forward, bool)

        if sign_with_master:
            signed_by = self.master_member
        else:
            signed_by = self.my_member

        messages = []
        global_time = self._timeline.claim_global_time()
        distribution = FullSyncDistribution(100, 100, 0.001)
        destination = CommunityDestination()
        for privilege_impl, permission_cls in permission_pairs:
            distribution_impl = distribution.implement(global_time, signed_by.claim_sequence_number())
            destination_impl = destination.implement()
            messages.append(Message(self, signed_by, distribution_impl, destination_impl, AuthorizePermission(privilege_impl, member, permission_cls)))

        if update_locally:
            for message in messages:
                assert self._timeline.check(message.signed_by, message.permission, message.distribution.global_time)
                self.on_authorize_message(None, message)

        if store_and_forward:
            self._dispersy.store_and_forward(messages)

        return messages

    def permit(self, permission, destination=(), sign_with_master=False, update_locally=True, store_and_forward=True):
        assert isinstance(permission, PermitPermission)
        assert isinstance(destination, tuple)
        assert isinstance(sign_with_master, bool)
        assert isinstance(update_locally, bool)
        assert isinstance(store_and_forward, bool)

        if sign_with_master:
            signed_by = self.master_member
        else:
            signed_by = self.my_member

        distribution = permission.privilege.distribution
        if isinstance(distribution, FullSyncDistribution):
            distribution_impl = distribution.implement(self._timeline.claim_global_time(), signed_by.claim_sequence_number())
        elif isinstance(distribution, LastSyncDistribution):
            distribution_impl = distribution.implement(self._timeline.claim_global_time())
        elif isinstance(distribution, DirectDistribution):
            distribution_impl = distribution.implement(self._timeline.global_time)
        else:
            raise ValueError("Unknown distribution")

        destination_impl = permission.privilege.destination.implement(*destination)

        message = Message(self, signed_by, distribution_impl, destination_impl, permission)

        if update_locally:
            assert self._timeline.check(message.signed_by, message.permission, message.distribution.global_time)
            self.on_message(None, message)

        if store_and_forward:
            self._dispersy.store_and_forward([message])

        return message

    def on_authorize_message(self, address, message):
        """
        A AuthorizePermission message was received, it was either
        locally generated or received from an external source.
        """
        assert isinstance(message, Message)
        self._timeline.update(message.signed_by, message.permission, message.distribution.global_time)

    def on_revoke_message(self, address, message):
        """
        A RevokePermission message was received, it was either locally
        generated or received from an external source.
        """
        assert isinstance(message, Message)
        self._timeline.update(message.signed_by, message.permission, message.distribution.global_time)

    def on_incoming_message(self, address, packet, message):
        """
        A message was received from an external source.
        """
        if __debug__:
            from Message import Message
        assert isinstance(address, tuple)
        assert isinstance(message, Message)
        if self._timeline.check(message.signed_by, message.permission, message.distribution.global_time):
            self._incoming_message_map[type(message.permission)](address, message)

        else:
            raise DelayMessageByProof()

    def on_message(self, address, message):
        """
        A message was received, it was either locally generated or
        received from an external source.

        Must be implemented in community specific code.
        """
        if __debug__:
            from Message import Message
        assert isinstance(message, (None, Message))
        raise NotImplemented()

    def get_privilege(self, name):
        """
        Returns the PrivilegeBase.Implementation subclass associated
        to NAME.  Or a KeyError if it does not exist.
        """
        assert isinstance(name, unicode)
        return self._privileges[name]

    def get_privileges(self):
        """
        Returns all the PrivilegeBase.Implementation subclasses
        available in this Community.
        """
        return self._privileges.itervalues()

    @staticmethod
    def get_dispersy_meta_privileges():
        """
        Returns the PrivilegeBase subclasses available to Dispersy in
        this Community.
        """
        return [PublicPrivilege(u"dispersy-sync", DirectDistribution(), CommunityDestination()),
                PublicPrivilege(u"dispersy-missing-sequence", DirectDistribution(), AddressDestination())]
#todo: dispersy-missing-global

    @staticmethod
    def get_meta_privileges():
        """
        Returns the PrivilegeBase subclasses available in this
        Community.
        """
        raise NotImplementedError()
