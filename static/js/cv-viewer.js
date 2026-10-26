/* The pipeline's CV viewer (core/job_detail.html).
 *
 * Opened by a row's CV button. Previous / Next walk the table's rows in the
 * order on screen -- the current filter and sort -- and load the next page
 * when the last loaded row is passed. Opening a CV marks it Seen; the quick
 * buttons set the recruiter status through the same endpoint as the table's
 * status picker, then move on. Nothing here sends an email the picker would
 * not send.
 */
(function () {
    'use strict';

    // Moving these candidates to Rejected can cancel a scheduled interview,
    // which emails the panel, so the viewer asks first.
    const EARLY = ['new', 'shortlisted', 'phone_screen'];

    function rowCell(pk, label) {
        return '#resume-row-' + pk + ' td[data-label="' + label + '"]';
    }

    window.cvViewer = function () {
        return {
            open: false,
            busy: false,
            cur: null,
            url: '',
            download: '',
            profile: '',
            name: '',
            type: '',
            score: '',
            status: '',
            position: 0,
            total: 0,
            hasPrev: false,
            hasNext: false,

            buttons() {
                return Array.from(document.querySelectorAll('#pipeline-tbody [data-cv-open]'));
            },

            // Rows are re-rendered by polling and status changes, so the
            // current one is found again by its uuid rather than by element.
            indexOfCurrent(list) {
                const uuid = this.cur && this.cur.dataset.uuid;
                return list.findIndex(function (b) { return b.dataset.uuid === uuid; });
            },

            show(btn) {
                if (!btn) return;
                const d = btn.dataset;
                this.cur = btn;
                this.url = d.cvUrl;
                this.download = d.cvDownload;
                this.profile = d.profileUrl;
                this.name = d.cvName;
                this.type = (d.cvType || (d.cvDownload || '').split('?')[0].split('.').pop() || '').toLowerCase();
                this.score = d.score;
                this.status = d.status;
                const list = this.buttons();
                const i = this.indexOfCurrent(list);
                const summary = document.getElementById('pipeline-queue-summary');
                this.position = i + 1;
                this.total = (summary && parseInt(summary.textContent, 10)) || list.length;
                this.hasPrev = i > 0;
                this.hasNext = i + 1 < list.length || !!document.querySelector('#pipeline-more button');
                this.open = true;
                this.markSeen(btn);
            },

            markSeen(btn) {
                const cell = document.querySelector(rowCell(btn.dataset.pk, 'Reviewed'));
                if (btn.dataset.seen === 'seen' || !window.htmx || !cell) return;
                btn.dataset.seen = 'seen';
                // The cell is the source as well as the target: a request from
                // nowhere inherits the page's hx-select="#main-content" and
                // would swap the cell for nothing.
                window.htmx.ajax('POST', btn.dataset.seenUrl, {
                    source: cell,
                    target: cell,
                    swap: 'outerHTML',
                    values: { seen_status: 'seen' },
                    headers: { 'X-CSRFToken': window.CSRF_TOKEN },
                });
            },

            prev() {
                const list = this.buttons();
                const i = this.indexOfCurrent(list);
                if (i > 0) this.show(list[i - 1]);
            },

            next() {
                const self = this;
                let list = this.buttons();
                const i = this.indexOfCurrent(list);
                if (i + 1 < list.length) return Promise.resolve(this.show(list[i + 1]));
                const more = document.querySelector('#pipeline-more button');
                if (!more || this.busy) return Promise.resolve();
                this.busy = true;
                return new Promise(function (resolve) {
                    let done = false;
                    // The next page has arrived once its swap has replaced the
                    // button; a live update or a Seen mark settling first
                    // would stop the wait too early.
                    function finish(e) {
                        if (done || (e && more.isConnected)) return;
                        done = true;
                        document.body.removeEventListener('htmx:afterSettle', finish);
                        self.busy = false;
                        list = self.buttons();
                        const j = self.indexOfCurrent(list);
                        if (j >= 0 && j + 1 < list.length) self.show(list[j + 1]);
                        else self.hasNext = !!document.querySelector('#pipeline-more button');
                        resolve();
                    }
                    document.body.addEventListener('htmx:afterSettle', finish);
                    setTimeout(finish, 15000);
                    more.click();
                });
            },

            setStatus(value) {
                const self = this;
                const btn = this.cur;
                if (!btn || this.busy || !window.htmx) return;
                const ask = value === 'rejected' && EARLY.indexOf(btn.dataset.status) === -1 && window.Swal
                    ? window.Swal.fire({
                        title: 'Reject ' + btn.dataset.cvName + '?',
                        text: 'They are past phone screening: any scheduled interview is cancelled and the panel is told.',
                        icon: 'warning',
                        showCancelButton: true,
                        confirmButtonText: 'Reject',
                        confirmButtonColor: '#e11d48',
                    }).then(function (r) { return r.isConfirmed; })
                    : Promise.resolve(true);
                ask.then(function (go) {
                    if (!go) return;
                    const pk = btn.dataset.pk;
                    const cell = document.querySelector(rowCell(pk, 'Recruiter Status'));
                    if (!cell) return;
                    self.busy = true;
                    window.htmx.ajax('POST', btn.dataset.statusUrl, {
                        source: cell,
                        target: cell,
                        swap: 'outerHTML',
                        values: { recruiter_status: value, context: 'cell' },
                        headers: { 'X-CSRFToken': window.CSRF_TOKEN },
                    }).then(function () {
                        self.busy = false;
                        const control = document.querySelector(rowCell(pk, 'Recruiter Status') + ' [data-current]');
                        const now = control ? control.dataset.current : value;
                        btn.dataset.status = now;
                        if (self.cur === btn) self.status = now;
                        // Refused by a rule (a toast says why): stay on this CV.
                        if (now === value) self.next();
                    }, function () { self.busy = false; });
                });
            },

            onKey(e) {
                if (!this.open || e.altKey || e.ctrlKey || e.metaKey) return;
                const tag = (e.target && e.target.tagName) || '';
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
                if (e.key === 'ArrowRight') { e.preventDefault(); this.next(); }
                else if (e.key === 'ArrowLeft') { e.preventDefault(); this.prev(); }
            },
        };
    };
})();

/* The pipeline's single live-update poll (core/job_detail.html) sends "pk:rank"
 * for every row still being screened or verified. With none on screen the
 * tick is dropped before it leaves, so an idle table costs the server nothing. */
window.pipelinePendingIds = function () {
    return Array.from(document.querySelectorAll('#pipeline-tbody tr[data-pending]'))
        .map(function (tr) { return tr.dataset.pk + ':' + (tr.dataset.rank || ''); })
        .join(',');
};
document.addEventListener('htmx:beforeRequest', function (e) {
    const elt = e.detail && e.detail.elt;
    if (elt && elt.id === 'pipeline-poller' && !window.pipelinePendingIds()) e.preventDefault();
});

/* A pipeline row's status picker keeps an empty options box; the full list
 * lives once per page in <template id="rs-options-template"> and is copied in
 * the first time the picker opens, marked with the row's current status. */
window.rsFillOptions = function (box) {
    const tpl = document.getElementById('rs-options-template');
    if (!box || box.childElementCount || !tpl) return;
    const holder = box.closest('[data-current]');
    const current = (holder && holder.dataset.current) || 'new';
    box.appendChild(tpl.content.cloneNode(true));
    box.querySelectorAll('[data-value]').forEach(function (btn) {
        const on = btn.dataset.value === current;
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) {
            btn.classList.add('status-picker__option--active', 'status-picker__option--' + btn.dataset.tone);
            const check = btn.querySelector('.status-picker__check');
            if (check) check.classList.add('status-picker__check--visible');
        }
        if (btn.dataset.value === 'hired' && !on && box.hasAttribute('data-hired-blocked')) {
            btn.disabled = true;
            btn.setAttribute('aria-disabled', 'true');
            btn.style.opacity = '.45';
            btn.style.cursor = 'not-allowed';
            btn.title = 'Complete the Pre-Onboarding checklist first';
        }
    });
};

/* Where the table's next page starts. Rows already loaded can leave the
 * filter -- shortlisted from the viewer while "New CV" is shown, or marked Seen
 * under "Not seen" -- and the server's list closes up behind them, so asking
 * for the next page at the plain offset would skip that many candidates. The
 * offset is the number of loaded rows that still match the filters. */
window.pipelineLoadedCount = function () {
    return document.querySelectorAll('#pipeline-tbody tr[id^="resume-row-"]').length;
};
window.pipelineNextOffset = function (fallback) {
    const field = function (id) { const el = document.getElementById(id); return (el && el.value) || 'all'; };
    const status = field('pipeline-status-filter');
    const seen = field('pipeline-seen-filter');
    const rows = document.querySelectorAll('#pipeline-tbody tr[id^="resume-row-"]');
    if (!rows.length) return fallback;
    let matching = 0;
    rows.forEach(function (tr) {
        const st = tr.querySelector('td[data-label="Recruiter Status"] [data-current]');
        const se = tr.querySelector('td[data-label="Reviewed"] [data-current]');
        if ((status === 'all' || !st || st.dataset.current === status)
                && (seen === 'all' || !se || se.dataset.current === seen)) matching += 1;
    });
    return matching;
};
// A candidate who applies while the table is open moves the list the other
// way; a row the next page brings twice is dropped.
document.addEventListener('htmx:afterSettle', function () {
    const seenIds = {};
    document.querySelectorAll('#pipeline-tbody tr[id^="resume-row-"]').forEach(function (tr) {
        if (seenIds[tr.id]) tr.remove(); else seenIds[tr.id] = true;
    });
});
