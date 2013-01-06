from django.core.urlresolvers import reverse
from django import forms
from django.forms import ValidationError
from django.shortcuts import redirect
from django.template import RequestContext
from django.utils.translation import ugettext as _
from misago.acl.utils import ACLError403, ACLError404
from misago.forms import Form, FormLayout, FormFields
from misago.forums.models import Forum
from misago.messages import Message
from misago.readstracker.trackers import ThreadsTracker
from misago.threads.forms import MoveThreadsForm, QuickReplyForm
from misago.threads.models import Thread, Post
from misago.threads.views.base import BaseView
from misago.views import error403, error404
from misago.utils import make_pagination

class ThreadView(BaseView):
    def fetch_thread(self, thread):
        self.thread = Thread.objects.get(pk=thread)
        self.forum = self.thread.forum
        self.proxy = Forum.objects.parents_aware_forum(self.forum)
        self.request.acl.forums.allow_forum_view(self.forum)
        self.request.acl.threads.allow_thread_view(self.request.user, self.thread)
        self.parents = Forum.objects.forum_parents(self.forum.pk, True)
        self.tracker = ThreadsTracker(self.request.user, self.forum)
    
    def fetch_posts(self, page):
        self.count = self.request.acl.threads.filter_posts(self.request, self.thread, Post.objects.filter(thread=self.thread)).count()
        self.posts = self.request.acl.threads.filter_posts(self.request, self.thread, Post.objects.filter(thread=self.thread)).prefetch_related('checkpoint_set', 'user', 'user__rank')
        if self.thread.merges > 0:
            self.posts = self.posts.order_by('merge', 'pk')
        else:
            self.posts = self.posts.order_by('pk')
        self.pagination = make_pagination(page, self.count, self.request.settings.posts_per_page)
        if self.request.settings.posts_per_page < self.count:
            self.posts = self.posts[self.pagination['start']:self.pagination['stop']]
        self.read_date = self.tracker.get_read_date(self.thread) 
        for post in self.posts:
            post.message = self.request.messages.get_message('threads_%s' % post.pk)
            post.is_read = post.date <= self.read_date
        last_post = self.posts[len(self.posts) - 1]
        if not self.tracker.is_read(self.thread):
            self.tracker.set_read(self.thread, last_post)
            self.tracker.sync()
            
    def get_post_actions(self):
        acl = self.request.acl.threads.get_role(self.thread.forum_id)
        actions = []
        try:
            if acl['can_approve'] and self.thread.replies_moderated > 0:
                actions.append(('accept', _('Accept posts')))
            if acl['can_move_threads_posts']:
                actions.append(('merge', _('Merge posts into one')))
                actions.append(('split', _('Split posts to new thread')))
                actions.append(('move', _('Move posts to other thread')))
            if acl['can_protect_posts']:
                actions.append(('protect', _('Protect posts')))
                actions.append(('unprotect', _('Remove posts protection')))
            if acl['can_delete_posts']:
                if self.thread.replies_deleted > 0:
                    actions.append(('undelete', _('Undelete posts')))
                actions.append(('soft', _('Soft delete posts')))
            if acl['can_delete_posts'] == 2:
                actions.append(('hard', _('Hard delete posts')))
        except KeyError:
            pass
        return actions
    
    def make_posts_form(self):
        self.posts_form = None
        list_choices = self.get_post_actions();
        if (not self.request.user.is_authenticated()
            or not list_choices):
            return
        
        form_fields = {}
        form_fields['list_action'] = forms.ChoiceField(choices=list_choices)
        list_choices = []
        for item in self.posts:
            list_choices.append((item.pk, None))
        if not list_choices:
            return
        form_fields['list_items'] = forms.MultipleChoiceField(choices=list_choices,widget=forms.CheckboxSelectMultiple)
        self.posts_form = type('PostsViewForm', (Form,), form_fields)
     
    def handle_posts_form(self):
        if self.request.method == 'POST' and self.request.POST.get('origin') == 'posts_form':
            self.posts_form = self.posts_form(self.request.POST, request=self.request)
            if self.posts_form.is_valid():
                checked_items = []
                for post in self.posts:
                    if str(post.pk) in self.posts_form.cleaned_data['list_items']:
                        checked_items.append(post.pk)
                if checked_items:
                    form_action = getattr(self, 'post_action_' + self.posts_form.cleaned_data['list_action'])
                    try:
                        response = form_action(checked_items)
                        if response:
                            return response
                        return redirect(self.request.path)
                    except forms.ValidationError as e:
                        self.message = Message(e.messages[0], 'error')
                else:
                    self.message = Message(_("You have to select at least one post."), 'error')
            else:
                if 'list_action' in self.posts_form.errors:
                    self.message = Message(_("Action requested is incorrect."), 'error')
                else:
                    self.message = Message(posts_form.non_field_errors()[0], 'error')
        else:
            self.posts_form = self.posts_form(request=self.request)
            
    def get_thread_actions(self):
        acl = self.request.acl.threads.get_role(self.thread.forum_id)
        actions = []
        try:
            if acl['can_approve'] and self.thread.moderated:
                actions.append(('accept', _('Accept this thread')))
            if acl['can_pin_threads'] == 2 and self.thread.weight < 2:
                actions.append(('annouce', _('Change this thread to annoucement')))
            if acl['can_pin_threads'] > 0 and self.thread.weight != 1:
                actions.append(('sticky', _('Change this thread to sticky')))
            if acl['can_pin_threads'] > 0:
                if self.thread.weight == 2:
                    actions.append(('normal', _('Change this thread to normal')))
                if self.thread.weight == 1:
                    actions.append(('normal', _('Unpin this thread')))
            if acl['can_move_threads_posts']:
                actions.append(('move', _('Move this thread')))
            if acl['can_close_threads']:
                if self.thread.closed:
                    actions.append(('open', _('Open this thread')))
                else:
                    actions.append(('close', _('Close this thread')))
            if acl['can_delete_threads']:
                if self.thread.deleted:
                    actions.append(('undelete', _('Undelete this thread')))
                else:
                    actions.append(('soft', _('Soft delete this thread')))
            if acl['can_delete_threads'] == 2:
                actions.append(('hard', _('Hard delete this thread')))
        except KeyError:
            pass
        return actions
    
    def make_thread_form(self):
        self.thread_form = None
        list_choices = self.get_thread_actions();
        if (not self.request.user.is_authenticated()
            or not list_choices):
            return      
        form_fields = {'thread_action': forms.ChoiceField(choices=list_choices)}
        self.thread_form = type('ThreadViewForm', (Form,), form_fields)
    
    def handle_thread_form(self):
        if self.request.method == 'POST' and self.request.POST.get('origin') == 'thread_form':
            self.thread_form = self.thread_form(self.request.POST, request=self.request)
            if self.thread_form.is_valid():
                form_action = getattr(self, 'thread_action_' + self.thread_form.cleaned_data['thread_action'])
                try:
                    response = form_action()
                    if response:
                        return response
                    return redirect(self.request.path)
                except forms.ValidationError as e:
                    self.message = Message(e.messages[0], 'error')
            else:
                if 'thread_action' in self.thread_form.errors:
                    self.message = Message(_("Action requested is incorrect."), 'error')
                else:
                    self.message = Message(form.non_field_errors()[0], 'error')
        else:
            self.thread_form = self.thread_form(request=self.request)

    def thread_action_accept(self):
        # Sync thread and post
        self.thread.moderated = False
        self.thread.replies_moderated -= 1
        self.thread.save(force_update=True)
        self.thread.start_post.moderated = False
        self.thread.start_post.save(force_update=True)
        self.thread.last_post.set_checkpoint(self.request, 'accepted')
        # Sync user
        if self.thread.last_post.user:
            self.thread.start_post.user.threads += 1
            self.thread.start_post.user.posts += 1
            self.thread.start_post.user.save(force_update=True)            
        # Sync forum
        self.forum.threads_delta += 1
        self.forum.posts_delta += self.thread.replies + 1
        self.forum.sync()
        self.forum.save(force_update=True)
        # Update monitor
        self.request.monitor['threads'] = int(self.request.monitor['threads']) + 1
        self.request.monitor['posts'] = int(self.request.monitor['posts']) + self.thread.replies + 1
        self.request.messages.set_flash(Message(_('Thread has been marked as reviewed and made visible to other members.')), 'success', 'threads')
    
    def thread_action_annouce(self):
        self.thread.weight = 2
        self.thread.save(force_update=True)
        self.request.messages.set_flash(Message(_('Thread has been turned into annoucement.')), 'success', 'threads')
    
    def thread_action_sticky(self):
        self.thread.weight = 1
        self.thread.save(force_update=True)
        self.request.messages.set_flash(Message(_('Thread has been turned into sticky.')), 'success', 'threads')
    
    def thread_action_normal(self):
        self.thread.weight = 0
        self.thread.save(force_update=True)
        self.request.messages.set_flash(Message(_('Thread weight has been changed to normal.')), 'success', 'threads')
    
    def thread_action_move(self):
        message = None
        if self.request.POST.get('do') == 'move':
            form = MoveThreadsForm(self.request.POST,request=self.request,forum=self.forum)
            if form.is_valid():
                new_forum = form.cleaned_data['new_forum']
                self.thread.forum = new_forum
                self.thread.post_set.update(forum=new_forum)
                self.thread.change_set.update(forum=new_forum)
                self.thread.checkpoint_set.update(forum=new_forum)
                self.thread.save(force_update=True)
                self.forum.sync()
                self.forum.save(force_update=True)
                self.request.messages.set_flash(Message(_('Thread has been moved to "%(forum)s".') % {'forum': new_forum.name}), 'success', 'threads')
                return None
            message = Message(form.non_field_errors()[0], 'error')
        else:
            form = MoveThreadsForm(request=self.request,forum=self.forum)
        return self.request.theme.render_to_response('threads/move.html',
                                                     {
                                                      'message': message,
                                                      'forum': self.forum,
                                                      'parents': self.parents,
                                                      'thread': self.thread,
                                                      'form': FormLayout(form),
                                                      },
                                                     context_instance=RequestContext(self.request));
        
    def thread_action_open(self):
        self.thread.closed = False
        self.thread.save(force_update=True)
        self.thread.last_post.set_checkpoint(self.request, 'opened')
        self.request.messages.set_flash(Message(_('Thread has been opened.')), 'success', 'threads')
        
    def thread_action_close(self):
        self.thread.closed = True
        self.thread.save(force_update=True)
        self.thread.last_post.set_checkpoint(self.request, 'closed')
        self.request.messages.set_flash(Message(_('Thread has been closed.')), 'success', 'threads')
    
    def thread_action_undelete(self):
        # Update thread
        self.thread.deleted = False
        self.thread.replies_deleted -= 1
        self.thread.save(force_update=True)
        # Update first post in thread
        self.thread.start_post.deleted = False
        self.thread.start_post.save(force_update=True)
        # Set checkpoint
        self.thread.last_post.set_checkpoint(self.request, 'undeleted')
        # Update forum
        self.forum.sync()
        self.forum.save(force_update=True)
        # Update monitor
        self.request.monitor['threads'] = int(self.request.monitor['threads']) + 1
        self.request.monitor['posts'] = int(self.request.monitor['posts']) + self.thread.replies + 1
        self.request.messages.set_flash(Message(_('Thread has been undeleted.')), 'success', 'threads')
    
    def thread_action_soft(self):
        # Update thread
        self.thread.deleted = True
        self.thread.replies_deleted += 1
        self.thread.save(force_update=True)
        # Update first post in thread
        self.thread.start_post.deleted = True
        self.thread.start_post.save(force_update=True)
        # Set checkpoint
        self.thread.last_post.set_checkpoint(self.request, 'deleted')
        # Update forum
        self.forum.sync()
        self.forum.save(force_update=True)
        # Update monitor
        self.request.monitor['threads'] = int(self.request.monitor['threads']) - 1
        self.request.monitor['posts'] = int(self.request.monitor['posts']) - self.thread.replies - 1
        self.request.messages.set_flash(Message(_('Thread has been deleted.')), 'success', 'threads')        
    
    def thread_action_hard(self):
        # Delete thread
        self.thread.delete()
        # Update forum
        self.forum.sync()
        self.forum.save(force_update=True)
        # Update monitor
        self.request.monitor['threads'] = int(self.request.monitor['threads']) - 1
        self.request.monitor['posts'] = int(self.request.monitor['posts']) - self.thread.replies - 1
        self.request.messages.set_flash(Message(_('Thread "%(thread)s" has been deleted.') % {'thread': self.thread.name}), 'success', 'threads')
        return redirect(reverse('forum', kwargs={'forum': self.forum.pk, 'slug': self.forum.slug}))
    
    def __call__(self, request, slug=None, thread=None, page=0):
        self.request = request
        self.pagination = None
        self.parents = None
        try:
            self.fetch_thread(thread)
            self.fetch_posts(page)
            self.make_thread_form()
            if self.thread_form:
                response = self.handle_thread_form()
                if response:
                    return response
            self.make_posts_form()
            if self.posts_form:
                response = self.handle_posts_form()
                if response:
                    return response
        except Thread.DoesNotExist:
            return error404(self.request)
        except ACLError403 as e:
            return error403(request, e.message)
        except ACLError404 as e:
            return error404(request, e.message)
        # Merge proxy into forum
        self.forum.closed = self.proxy.closed
        return request.theme.render_to_response('threads/thread.html',
                                                {
                                                 'message': request.messages.get_message('threads'),
                                                 'forum': self.forum,
                                                 'parents': self.parents,
                                                 'thread': self.thread,
                                                 'is_read': self.tracker.is_read(self.thread),
                                                 'count': self.count,
                                                 'posts': self.posts,
                                                 'pagination': self.pagination,
                                                 'quick_reply': FormFields(QuickReplyForm(request=request)).fields,
                                                 'thread_form': FormFields(self.thread_form).fields if self.thread_form else None,
                                                 'posts_form': FormFields(self.posts_form).fields if self.posts_form else None,
                                                 },
                                                context_instance=RequestContext(request));