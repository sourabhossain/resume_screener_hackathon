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
                if (btn.dataset.seen === 'seen' || !window.htmx) return;
                btn.dataset.seen = 'seen';
                window.htmx.ajax('POST', btn.dataset.seenUrl, {
                    target: rowCell(btn.dataset.pk, 'Reviewed'),
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
                    function finish() {
                        if (done) return;
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
                    self.busy = true;
                    const pk = btn.dataset.pk;
                    window.htmx.ajax('POST', btn.dataset.statusUrl, {
                        target: rowCell(pk, 'Recruiter Status'),
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
