"""
The Trigger module provides the objects that sit and wait for incoming
messages.  Each message that was successfully processed may 'trigger'
one of the Trigger objects defined in this module.

Triggers allow us to wait for something, for instance, when a message
is received out of sequence it is delayed until the previous message
in the sequence is successfully processed.  Hence, processing this
previous message will trigger the processing of the delayed message.

@author: Boudewijn Schoon
@organization: Technical University Delft
@contact: dispersy@frayja.com
"""

from re import compile as expression_compile

if __debug__:
    from Print import dprint

class Trigger(object):
    def on_message(self, address, message):
        """
        Called with a received message.

        Must return True to keep the trigger available.  Hence,
        returning False will remove the trigger.
        """
        raise NotImplementedError()

    def on_timeout(self):
        raise NotImplementedError()

class TriggerCallback(Trigger):
    def __init__(self, pattern, response_func, response_args, max_responses):
        """
        Receiving a message matching PATTERN triggers a call to
        RESPONSE_FUNC.

        PATTERN is a python regular expression string.

        RESPONSE_FUNC is called when PATTERN matches the incoming
        message footprint.  The first argument is the sender address,
        the second argument is the incoming message, following this
        are optional values from RESPONSE_ARGS.

        RESPONSE_ARGS is an optional tuple containing arguments passed
        to RESPONSE_ARGS.

        MAX_RESPONSES is a number.  Once MAX_RESPONSES messages are
        received no further calls are made to RESPONSE_FUNC.

        When a timeout is received and MAX_RESPONSES has not yet been
        reached, RESPONSE_FUNC is immediately called.  The first
        argument will be ('', -1), the second will be None, following
        this are the optional values from RESPONSE_FUNC.
        """
        assert isinstance(pattern, str)
        assert hasattr(response_func, "__call__")
        assert isinstance(response_args, tuple)
        assert isinstance(max_responses, int)
        assert max_responses > 0
        if __debug__:
            self._debug_pattern = pattern
        self._match = expression_compile(pattern).match
        self._response_func = response_func
        self._response_args = response_args
        self._responses_remaining = max_responses

        dprint(self._response_args)

    def on_message(self, address, message):
        if __debug__:
            dprint("Does it match? ", bool(self._responses_remaining > 0 and self._match(message.footprint)))
            dprint("Expression: ", self._debug_pattern)
            dprint(" Footprint: ", message.footprint)
        if self._responses_remaining > 0 and self._match(message.footprint):
            self._responses_remaining -= 1
            # note: this callback may raise DelayMessage, etc
            self._response_func(address, message, *self._response_args)

        # False to remove the Trigger
        return self._responses_remaining > 0

    def on_timeout(self):
        if self._responses_remaining > 0:
            self._responses_remaining = 0
            # note: this callback may raise DelayMessage, etc
            self._response_func(("", -1), None, *self._response_args)

class TriggerPacket(Trigger):
    def __init__(self, pattern, on_incoming_packets, packets):
        """
        Receiving a message matching PATTERN triggers a call to the
        on_incoming_packet method with PACKETS.

        PATTERN is a python regular expression string.

        ON_INCOMING_PACKETS is called when PATTERN matches the
        incoming message footprint.  The only argument is PACKETS.

        PACKETS is a list containing (address, packet) tuples.  These
        packets are effectively delayed until a message matching
        PATTERN was received.

        When a timeout is received this Trigger is removed and PACKETS
        are lost.
        """
        if __debug__:
            assert isinstance(pattern, str)
            assert hasattr(on_incoming_packets, "__call__")
            assert isinstance(packets, (tuple, list))
            assert len(packets) > 0
            for packet in packets:
                assert isinstance(packet, tuple)
                assert len(packet) == 2
                assert isinstance(packet[0], tuple)
                assert len(packet[0]) == 2
                assert isinstance(packet[0][0], str)
                assert isinstance(packet[0][1], int)
                assert isinstance(packet[1], str)
            self._debug_pattern = pattern
        self._match = expression_compile(pattern).match
        self._on_incoming_packets = on_incoming_packets
        self._packets = packets

    def on_message(self, address, message):
        if __debug__:
            dprint("Does it match? ", bool(self._match and self._match(message.footprint)))
            dprint("Expression: ", self._debug_pattern)
            dprint(" Footprint: ", message.footprint)
        if self._match:
            if self._match(message.footprint):
                self._on_incoming_packets(self._packets)
                # False to remove the Trigger, because we handled the
                # Trigger
                return False
            else:
                # True to keep the Trigger, because we did not handle
                # the Trigger yet
                return True
        else:
            # False to remove the Trigger, because the Trigger
            # timed-out
            return False

    def on_timeout(self):
        if self._match:
            self._match = None

class TriggerMessage(Trigger):
    def __init__(self, pattern, on_incoming_message, address, message):
        """
        Receiving a message matching PATTERN triggers a call to the
        on_incoming_message message with ADDRESS and MESSAGE.

        PATTERN is a python regular expression string.

        ON_INCOMING_MESSAGE is called when PATTERN matches the
        incoming message footprint.  The first argument is ADDRESS,
        the second argument is MESSAGE.

        ADDRESS and MESSAGE are a Message.Implementation and the
        address from where this was received.  This message is
        effectively delayed until a message matching PATTERN is
        received.

        When a timeout is received this Trigger is removed MESSAGE is
        lost.
        """
        if __debug__:
            from Message import Message
        assert isinstance(pattern, str)
        assert hasattr(on_incoming_message, "__call__")
        assert isinstance(address, tuple)
        assert len(address) == 2
        assert isinstance(address[0], str)
        assert isinstance(address[1], int)
        assert isinstance(message, Message.Implementation)
        if __debug__:
            self._debug_pattern = pattern
        self._match = expression_compile(pattern).match
        self._on_incoming_message = on_incoming_message
        self._address = address
        self._message = message

    def on_message(self, address, message):
        if __debug__:
            dprint("Does it match? ", bool(self._match and self._match(message.footprint)))
            dprint("Expression: ", self._debug_pattern)
            dprint(" Footprint: ", message.footprint)
        if self._match:
            if self._match(message.footprint):
                self._on_incoming_message(self._address, self._message)
                # False to remove the Trigger, because we handled the
                # Trigger
                return False
            else:
                # True to keep the Trigger, because we did not handle
                # the Trigger yet
                return True
        else:
            # False to remove the Trigger, because the Trigger
            # timed-out
            return False

    def on_timeout(self):
        if self._match:
            self._match = None
