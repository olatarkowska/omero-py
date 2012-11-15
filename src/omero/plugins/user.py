#!/usr/bin/env python
"""
   User administration plugin

   Copyright 2009 Glencoe Software, Inc. All rights reserved.
   Use is subject to license terms supplied in LICENSE.txt

"""

import os
import sys

from omero.cli import UserGroupControl, CLI, ExceptionHandler
from omero.rtypes import unwrap as _

HELP = "Support for adding and managing users"

class UserControl(UserGroupControl):

    def _configure(self, parser):

        self.exc = ExceptionHandler()

        sub = parser.sub()

        add = parser.add(sub, self.add, help = "Add user")
        add.add_argument("--ignore-existing", action="store_true", default=False, help="Do not fail if user already exists")
        add.add_argument("-m", "--middlename", help = "Middle name, if available")
        add.add_argument("-e", "--email")
        add.add_argument("-i", "--institution")
        # Capitalized since conflict with main values
        add.add_argument("-P", "--userpassword", help = "Password for user")
        add.add_argument("-a", "--admin", action="store_true", help = "Whether the user should be an admin")
        add.add_argument("username", help = "User's login name")
        add.add_argument("firstname", help = "User's given name")
        add.add_argument("lastname", help = "User's surname name")
        add.add_argument("member_of", nargs="+", help = "Groups which the user is to be a member of")

        list = parser.add(sub, self.list, help = "List current users")

        password = parser.add(sub, self.password, help = "Set user's password")
        password.add_argument("username", nargs="?", help = "Username if not the current user")

        email = parser.add(sub, self.email, help = "List users' email addresses")
        email.add_argument("-n", "--names", action="store_true", default=False, help = "Print user names along with email addresses")
        email.add_argument("-1", "--one", action="store_true", default=False, help = "Print one user per line")
        email.add_argument("-i", "--ignore", action="store_true", default=False, help = "Ignore users without email addresses")

        joingroup = parser.add(sub, self.joingroup, "Join one or more groups")
        joingroup.add_argument("GROUP", metavar="group", nargs="+", help = "ID or name of the group to join")
        joingroup.add_argument("--as-owner", action="store_true", default=False, help="Join the group as an owner")

        leavegroup = parser.add(sub, self.leavegroup, "Leave one or more groups")
        leavegroup.add_argument("GROUP", metavar="group", nargs="+", help = "ID or name of the group to leave")
        leavegroup.add_argument("--as-owner", action="store_true", default=False, help="Leave the owner list of the group")

        for x in (joingroup, leavegroup):
            group = x.add_mutually_exclusive_group()
            group.add_argument("--id", help="ID of the user. Default to the current user")
            group.add_argument("--name", help="Name of the user. Default to the current user")


    def format_name(self, exp):
        record = ""
        fn = _(exp.firstName)
        mn = " "
        if _(exp.middleName):
            mn = " %s " % _(exp.middleName)
        ln = _(exp.lastName)
        record += "%s%s%s" % (fn, mn, ln)
        return record

    def email(self, args):
        c = self.ctx.conn(args)
        a = c.sf.getAdminService()

        skipped = []
        records = []
        for exp in a.lookupExperimenters():

            # Handle users without email
            if not _(exp.email):
                if not args.ignore:
                    skipped.append(exp)
                continue

            record = ""
            if args.names:
                record += '"%s"' % self.format_name(exp)
                record += " <%s>" % _(exp.email)
            else:
                record += _(exp.email)

            records.append(record)

        if args.one:
            for record in records:
                self.ctx.out(record)
        else:
            self.ctx.out(", ".join(records))

        if skipped:
            self.ctx.err("Missing email addresses:")
            for s in skipped:
                self.ctx.err(self.format_name(s))

    def password(self, args):
        import omero
        from omero.rtypes import rstring
        client = self.ctx.conn(args)
        own_name = self.ctx._event_context.userName
        admin = client.sf.getAdminService()

        # tickets 3202, 5841
        own_pw = self._ask_for_password(" for your user (%s)" % own_name, strict = False)
        try:
            client.sf.setSecurityPassword(own_pw)
            self.ctx.out("Verified password.\n")
        except omero.SecurityViolation, sv:
            import traceback
            self.ctx.die(456, "SecurityViolation: Bad credentials")
            self.ctx.dbg(traceback.format_exc(sv))

        if args.username:
            self.ctx.out("Changing password for %s" % args.username)
        else:
            self.ctx.out("Changing password for %s" % own_name)

        pw = self._ask_for_password(" to be set")
        pw = rstring(pw)
        if args.username:
            admin.changeUserPassword(args.username, pw)
        else:
            admin.changePassword(pw)
        self.ctx.out("Password changed")

    def list(self, args):
        c = self.ctx.conn(args)
        a = c.sf.getAdminService()
        users = a.lookupExperimenters()
        roles = a.getSecurityRoles()
        user_group = roles.userGroupId
        sys_group = roles.systemGroupId

        from omero.util.text import TableBuilder
        tb = TableBuilder("id", "omeName", "firstName", "lastName", "email", \
            "active", "admin", "member of", "leader of")

        users.sort(lambda a,b: cmp(a.id.val, b.id.val))
        for user in users:
            row = [user.id.val, user.omeName.val, user.firstName.val, user.lastName.val]
            row.append(user.email and user.email.val or "")
            active = ""
            admin = ""
            member_of = []
            leader_of = []
            for x in user.copyGroupExperimenterMap():
                if not x:
                    continue
                gid = x.parent.id.val
                if user_group == gid:
                    active = "Yes"
                elif sys_group == gid:
                    admin = "Yes"
                elif x.owner.val:
                    leader_of.append(str(gid))
                else:
                    member_of.append(str(gid))

            row.append(active)
            row.append(admin)

            if member_of:
                row.append(",".join(member_of))
            else:
                row.append("")
            if leader_of:
                row.append(",".join(leader_of))
            else:
                row.append("")

            tb.row(*tuple(row))
        self.ctx.out(str(tb.build()))

    def add(self, args):
        email = args.email
        login = args.username
        first = args.firstname
        middle = args.middlename
        last = args.lastname
        inst = args.institution
        pasw = args.userpassword

        import omero
        from omero.rtypes import rstring
        from omero_model_ExperimenterI import ExperimenterI as Exp
        from omero_model_ExperimenterGroupI import ExperimenterGroupI as Grp
        c = self.ctx.conn(args)
        p = c.ic.getProperties()
        e = Exp()
        e.omeName = rstring(login)
        e.firstName = rstring(first)
        e.lastName = rstring(last)
        e.middleName = rstring(middle)
        e.email = rstring(email)
        e.institution = rstring(inst)
        admin = c.getSession().getAdminService()

        try:
            usr = admin.lookupExperimenter(login)
            if usr:
                if args.ignore_existing:
                    self.ctx.out("User exists: %s (id=%s)" % (login, usr.id.val))
                    return
                else:
                    self.ctx.die(3, "User exists: %s (id=%s)" % (login, usr.id.val))
        except omero.ApiUsageException, aue:
            pass # Apparently no such user exists

        try:
            groups = [admin.lookupGroup(group) for group in args.member_of]
        except omero.ApiUsageException, aue:
            self.ctx.die(68, aue.message)

        roles = admin.getSecurityRoles()
        groups.append(Grp(roles.userGroupId, False))
        if args.admin:
            groups.append(Grp(roles.systemGroupId, False))

        group = groups.pop(0)

        try:
            if pasw is None:
                id = admin.createExperimenter(e, group, groups)
                self.ctx.out("Added user %s" % id)
            else:
                id = admin.createExperimenterWithPassword(e, rstring(pasw), group, groups)
                self.ctx.out("Added user %s with password" % id)
        except omero.ValidationException, ve:
            # Possible, though unlikely after previous check
            if self.exc.is_constraint_violation(ve):
                self.ctx.die(66, "User already exists: %s" % login)
            else:
                self.ctx.die(67, "Unknown ValidationException: %s" % ve.message)
        except omero.SecurityViolation, se:
            self.ctx.die(68, "Security violation: %s" % se.message)

    def parse_userid(self, a, args):
        if args.id:
            user = getattr(args, "id", None)
            return self.find_user_by_id(a, user, fatal = True)
        elif args.name:
            user = getattr(args, "name", None)
            return self.find_user_by_name(a, user, fatal = True)
        else:
            user = self.ctx._event_context.userName
            return self.find_user_by_name(a, user, fatal=True)

    def list_groups(self, a, groups):

        group_list = []
        for group in groups:
            [gid, g] = self.find_group(a, group, fatal = False)
            if g:
                group_list.append(g)
        if not group_list:
            self.error_no_group_found(fatal = True)

        return group_list

    def filter_groups(self, groups, uid, owner = False, join = True):

        for group in list(groups):
            if owner:
                uid_list = self.getownerids(group)
                relation = "owner of"
            else:
                uid_list = self.getuserids(group)
                relation = "in"

            if join:
                if uid in uid_list:
                    self.ctx.out("%s is already %s group %s" % (uid, relation, group.id.val))
                    groups.remove(group)
            else:
                if uid not in uid_list:
                    self.ctx.out("%s is not %s group %s" % (uid, relation, group.id.val))
                    groups.remove(group)
        return groups

    def joingroup(self, args):
        import omero
        c = self.ctx.conn(args)
        a = c.sf.getAdminService()

        uid, username = self.parse_userid(a, args)
        groups = self.list_groups(a, args.GROUP)
        groups = self.filter_groups(groups, uid, args.as_owner, True)

        for group in groups:
            if args.as_owner:
                self.addownersbyid(a, group, [uid])
            else:
                self.addusersbyid(a, group, [uid])

    def leavegroup(self, args):
        import omero
        c = self.ctx.conn(args)
        a = c.sf.getAdminService()

        uid, username = self.parse_userid(a, args)
        groups = self.list_groups(a, args.GROUP)
        groups = self.filter_groups(groups, uid, args.as_owner, False)

        for group in list(groups):
            if args.as_owner:
                self.removeownersbyid(a, group, [uid])
            else:
                self.removeusersbyid(a, group, [uid])
try:
    register("user", UserControl, HELP)
except NameError:
    if __name__ == "__main__":
        cli = CLI()
        cli.register("user", UserControl, HELP)
        cli.invoke(sys.argv[1:])

