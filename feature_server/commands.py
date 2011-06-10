# Copyright (c) Mathias Kaerlev 2011.

# This file is part of pyspades.

# pyspades is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# pyspades is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with pyspades.  If not, see <http://www.gnu.org/licenses/>.

import inspect
import random
import time
from twisted.internet import reactor

class InvalidPlayer(Exception):
    pass

class InvalidTeam(Exception):
    pass

def admin(func):
    def new_func(connection, *arg, **kw):
        if not connection.admin:
            return 'No administrator rights!'
        func(connection, *arg, **kw)
    new_func.func_name = func.func_name
    new_func.admin = True
    return new_func

def name(name):
    def dec(func):
        func.func_name = name
        return func
    return dec

def get_player(protocol, value):
    try:
        if value.startswith('#'):
            value = int(value[1:])
            return protocol.players[value][0]
        players = protocol.players
        try:
            return players[value][0]
        except KeyError:
            value = value.lower()
            for player in players.values():
                if player.name.lower().count(value):
                    return player
    except (KeyError, IndexError, ValueError):
        pass
    raise InvalidPlayer()

def get_team(connection, value):
    value = value.lower()
    if value == 'blue':
        return connection.protocol.blue_team
    elif value == 'green':
        return connection.protocol.green_team
    raise InvalidTeam()

def join_arguments(arg, default = None):
    if not arg:
        return default
    return ' '.join(arg)

@admin
def kick(connection, value, *arg):
    reason = join_arguments(arg)
    player = get_player(connection.protocol, value)
    player.kick(reason)

@admin
def ban(connection, value, *arg):
    reason = join_arguments(arg)
    player = get_player(connection.protocol, value)
    player.ban(reason)

@admin
def say(connection, *arg):
    value = ' '.join(arg)
    connection.protocol.send_chat(value)
    connection.protocol.irc_say(value)

@admin
def kill(connection, value):
    player = get_player(connection.protocol, value)
    player.kill()
    message = '%s killed %s' % (connection.name, player.name)
    connection.protocol.send_chat(message, irc = True)

@admin
def heal(connection, player = None):
    if player is not None:
        player = get_player(connection.protocol, player)
        message = '%s was healed by %s' % (player.name, connection.name)
    else:
        player = connection
        message = '%s was healed' % (connection.name)
    player.refill()
    connection.protocol.send_chat(message, irc = True)

def votekick(connection, value):
    player = get_player(connection.protocol, value)
    return connection.protocol.start_votekick(connection, player)

@name('y')
def vote_yes(connection):
    connection.protocol.votekick(connection, True)

@name('n')
def vote_no(connection):
    connection.protocol.votekick(connection, False)

@name('cancel')
def cancel_vote(connection):
    return connection.protocol.cancel_votekick(connection)

def rules(connection):
    lines = connection.protocol.rules
    if lines is None:
        return
    connection.send_lines(lines)

def help(connection):
    """
    This help
    """
    names = [command.func_name for command in command_list
        if hasattr(command, 'admin') in (connection.admin, False)]
    return 'Available commands: %s' % (', '.join(names))

def login(connection, password):
    """
    Login as admin
    """
    passwords = connection.protocol.admin_passwords
    if password in passwords:
        connection.admin = True
        message = '%s logged in as admin' % connection.name
        connection.protocol.send_chat(message, irc = True)
        return None
    if connection.login_retries is None:
        connection.login_retries = connection.protocol.login_retries - 1
    else:
        connection.login_retries -= 1
    if not connection.login_retries:
        connection.kick('Ran out of login attempts')
        return
    return 'Invalid password - you have %s tries left' % (
        connection.login_retries)

def pm(connection, value, *arg):
    player = get_player(connection.protocol, value)
    message = join_arguments(arg)
    player.send_chat('PM from %s: %s' % (connection.name, message))
    return 'PM sent to %s' % player.name

def follow(connection, player = None):
    """Follow a player; on your next spawn, you'll spawn at their position,
        similar to the squad spawning feature of Battlefield."""
    if player is None:
        if connection.follow is None:
            return "You aren't following anybody. To follow a player say /follow <nickname>"
        else:
            player = connection.follow
            connection.follow = None
            connection.respawn_time = connection.protocol.respawn_time
            player.send_chat('%s is no longer following you.' % connection.name)
            return 'You are no longer following %s.' % player.name
    
    player = get_player(connection.protocol, player)
    if connection == player:
        return "You can't follow yourself!"
    if not connection.team == player.team:
        return '%s is not on your team.' % player.name
    if connection.follow == player:
        return "You're already following %s" % player.name
    if not player.followable:
        return "%s doesn't want to be followed." % player.name
    if len(player.get_followers()) >= connection.protocol.max_followers:
        return '%s has too many followers!' % player.name
    connection.follow = player
    connection.respawn_time = connection.protocol.follow_respawn_time
    player.send_chat('%s is now following you.' % connection.name)
    return ('Next time you die you will spawn where %s is. To stop, type /follow' %
        player.name)

@name('nofollow')
def no_follow(connection):
    connection.followable = not connection.followable
    if not connection.followable:
        connection.drop_followers()
    return 'Teammates will %s be able to follow you.' % (
        'now' if connection.followable else 'no longer')

@admin
def lock(connection, value):
    team = get_team(connection, value)
    team.locked = True
    connection.protocol.send_chat('%s team is now locked' % team.name)
    connection.protocol.irc_say('* %s locked %s team' % (connection.name, 
        team.name))

@admin
def unlock(connection, value):
    team = get_team(connection, value)
    team.locked = False
    connection.protocol.send_chat('%s team is now unlocked' % team.name)
    connection.protocol.irc_say('* %s unlocked %s team' % (connection.name, 
        team.name))

@admin
def switch(connection, value = None):
    if value is not None:
        connection = get_player(connection.protocol, value)
    connection.team = connection.team.other
    connection.kill()
    connection.protocol.send_chat('%s has switched teams' % connection.name)

@name('setbalance')
@admin
def set_balance(connection, value):
    try:
        value = int(value)
    except ValueError:
        return 'Invalid value %r. Use 0 for off, 1 and up for on' % value
    protocol = connection.protocol
    protocol.balanced_teams = value
    protocol.send_chat('Balanced teams set to %s' % value)
    connection.protocol.irc_say('* %s set balanced teams to %s' % (
        connection.name, value))

@name('togglebuild')
@admin
def toggle_build(connection):
    value = not connection.protocol.building
    connection.protocol.building = value
    on_off = ['OFF', 'ON'][int(value)]
    connection.protocol.send_chat('Building has been toggled %s!' % on_off)
    connection.protocol.irc_say('* %s toggled building %s' % (connection.name, 
        on_off))
    
@name('togglekill')
@admin
def toggle_kill(connection):
    value = not connection.protocol.killing
    connection.protocol.killing = value
    on_off = ['OFF', 'ON'][int(value)]
    connection.protocol.send_chat('Killing has been toggled %s!' % on_off)
    connection.protocol.irc_say('* %s toggled killing %s' % (connection.name, 
        on_off))

@name('toggleteamkill')
@admin
def toggle_teamkill(connection):
    value = not connection.protocol.friendly_fire
    connection.protocol.friendly_fire = value
    on_off = ['OFF', 'ON'][int(value)]
    connection.protocol.send_chat('Friendly fire has been toggled %s!' % on_off)
    connection.protocol.irc_say('* %s toggled friendly fire %s' % (
        connection.name, on_off))

@admin
def mute(connection, value):
    player = get_player(connection.protocol, value)
    player.mute = True
    message = '%s has been muted by %s' % (player.name, connection.name)
    connection.protocol.send_chat(message, irc = True)

@admin
def unmute(connection, value):
    player = get_player(connection.protocol, value)
    player.mute = False
    message = '%s has been unmuted by %s' % (player.name, connection.name)
    connection.protocol.send_chat(message, irc = True)

@admin
def teleport(connection, player1, player2 = None):
    player1 = get_player(connection.protocol, player1)
    if player2 is not None:
        player, target = player1, get_player(connection.protocol, player2)
        message = '%s teleported %s to %s' % (connection.name, player.name, 
            target.name)
    else:
        player, target = connection, player1
        message = '%s teleported to %s' % (connection.name, target.name)

    # set location!
    player.set_location(target.get_location())
    connection.protocol.send_chat(message, irc = True)

from pyspades.common import coordinates

@admin
def goto(connection, value):
    x, y = coordinates(value)
    x += 32
    y += 32
    connection.set_location((x, y, connection.protocol.map.get_height(x, y)))
    message = '%s teleported to location %s' % (connection.name, value.upper())
    connection.protocol.send_chat(message, irc = True)

@admin
def god(connection, value = None):
    if value is not None:
        connection = get_player(connection.protocol, value)
    connection.god = not connection.god
    if connection.god:
        message = '%s entered GOD MODE!' % connection.name
    else:
        message = '%s returned to being a mere human.' % connection.name
    connection.protocol.send_chat(message, irc = True)

@admin
def reset_game(connection):
    connection.reset_game()
    connection.protocol.send_chat('Game has been reset by %s' % connection.name,
        irc = True)

from pyspades.server import grenade_packet, position_data, orientation_data
from pyspades.collision import distance_3d_vector

def pick_aux_connection(connection):
    best = None
    best_distance = 0.0
    for player in connection.team.get_players():
        distance = distance_3d_vector(connection.position, player.position)
        if best is None or player.hp <= 0 and best.hp > 0:
            best, best_distance = player, distance
            continue
        if player.hp > 0 and best.hp <= 0:
            continue
        if distance > best_distance:
            best, best_distance = player, distance
    return best

def prepare_packet_data(data, x, y, z, player_id = None):
    data.x = x
    data.y = y
    data.z = z
    data.player_id = player_id

def send_contained_ex(connection, what, only_to = None, exclude = None):
    if only_to is not None:
        only_to.send_contained(what)
    else:
        connection.protocol.send_contained(what, sender = exclude)

def teleport_and_send(connection, packets, x, y, z,
                      only_to = None, exclude = None):
    start_x, start_y, start_z = connection.get_location()
    prepare_packet_data(position_data, x, y, z, connection.player_id)
    send_contained_ex(connection, position_data, only_to, exclude)
    for packet in packets:
        packet.player_id = connection.player_id
        send_contained_ex(connection, packet, only_to, exclude)
    prepare_packet_data(position_data, start_x, start_y, start_z,
        connection.player_id)
    send_contained_ex(connection, position_data, only_to, exclude)

def desync_grenade(connection, x, y, z, fuse):
    prepare_packet_data(orientation_data,
        1.0 if connection.team.id == 0 else -1.0, 0.0, 0.0)
    grenade_packet.value = fuse
    packets = [orientation_data, grenade_packet]
    if connection.aux is None:
        connection.aux = pick_aux_connection(connection)
    if connection is not connection.aux:
        teleport_and_send(connection, packets, x, y, z, exclude = connection)
        teleport_and_send(connection.aux, packets, x, y, z, only_to = connection)
    else:
        teleport_and_send(connection, packets, x, y, z)

@admin
def airstrike(connection, value):
    start_x, start_y = coordinates(value)
    start_z = 1
    connection.aux = pick_aux_connection(connection)
    for i in xrange(16):
        x, y = start_x + random.randrange(64), start_y + random.randrange(64)
        height = connection.protocol.map.get_height(x, y)
        reactor.callLater(i * 0.45, desync_grenade, connection, x, y, start_z,
            height * 0.037) #2.4

@admin
def airstrikeb(connection, value):
    start_x, start_y = coordinates(value)
    start_z = 1
    increment_x = 6
    connection.aux = pick_aux_connection(connection)
    for r in xrange(5):
        x, y = start_x + random.randrange(64), start_y + random.randrange(64)
        fuse = connection.protocol.map.get_height(x, y) * 0.037
        for i in xrange(5):
            x += increment_x
            reactor.callLater(r * 1.25 + i * 0.15, desync_grenade, connection,
                x, y, start_z, fuse) #2.4

@admin
def rollmap(connection, filename = None, value = None):
    start_x, start_y, end_x, end_y = 0, 0, 512, 512
    if filename is None:
        filename = connection.protocol.map_info.filename
    if value is not None:
        start_x, start_y = coordinates(value)
        end_x, end_y = start_x + 64, start_y + 64
    return connection.protocol.start_rollback(connection, filename,
        start_x, start_y, end_x, end_y)

@admin
def rollback(connection, value = None):
    return rollmap(connection, value = value)

@admin
def rollbackcancel(connection):
    connection.protocol.end_rollback(connection)
    
@admin
def tweak(connection, var, value):
    if var == 'rows':
        connection.protocol.rollback_max_rows_per_cycle = int(value)
    elif var == 'packets':
        connection.protocol.rollback_max_packets_per_cycle = int(value)
    elif var == 'time':
        connection.protocol.rollback_time_between_cycles = float(value)
    elif var == 'enabled':
        connection.protocol.airstrike_enabled = (value != '0')
    elif var == 'minscore':
        connection.protocol.airstrike_min_score_req = int(value)
    elif var == 'streak':
        connection.protocol.airstrike_streak_req = int(value)

command_list = [
    help,
    pm,
    login,
    kick,
    votekick,
    vote_yes,
    vote_no,
    cancel_vote,
    ban,
    mute,
    unmute,
    say,
    kill,
    heal,
    lock,
    unlock,
    switch,
    set_balance,
    rules,
    toggle_build,
    toggle_kill,
    toggle_teamkill,
    teleport,
    goto,
    god,
    follow,
    no_follow,
    reset_game,
    airstrike,
    airstrikeb,
    rollmap,
    rollback,
    rollbackcancel,
    tweak
]

commands = {}

for command_func in command_list:
    commands[command_func.func_name] = command_func

def handle_command(connection, command, parameters):
    command = command.lower()
    try:
        command_func = commands[command]
    except KeyError:
        return 'Invalid command'
    #try:
    return command_func(connection, *parameters)
    #except TypeError:
        #return 'Invalid number of arguments for %s' % command
    #except InvalidPlayer:
        #return 'No such player'
    #except InvalidTeam:
        #return 'Invalid team specifier'
    #except ValueError:
        #return 'Invalid parameters'