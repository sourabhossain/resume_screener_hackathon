/**
 * Custom dropdown pickers — Alpine components for forms across the app.
 * Registered before Alpine.start() so HTMX swaps can re-init via Alpine.initTree.
 */
document.addEventListener('alpine:init', () => {
    const CHOICE_PRESETS = {
        job_status: {
            menuTitle: 'Job status',
            menuSubtitle: 'Control whether candidates can see and apply to this role',
            tones: { draft: 'zinc', active: 'emerald', closed: 'rose' },
            hints: {
                draft: 'Hidden from careers page',
                active: 'Open for applications',
                closed: 'No longer accepting applicants',
            },
        },
        employment_type: {
            menuTitle: 'Employment type',
            menuSubtitle: 'How this role is staffed',
            tones: {
                full_time: 'indigo',
                part_time: 'sky',
                contract: 'violet',
                freelance: 'cyan',
                internship: 'amber',
            },
            hints: {
                full_time: 'Standard full-time hours',
                part_time: 'Reduced weekly hours',
                contract: 'Fixed-term engagement',
                freelance: 'Project-based work',
                internship: 'Training or entry-level role',
            },
        },
        location_type: {
            menuTitle: 'Location type',
            menuSubtitle: 'Where work happens',
            tones: { on_site: 'zinc', remote: 'sky', hybrid: 'violet' },
            hints: {
                on_site: 'Work from office',
                remote: 'Work from anywhere',
                hybrid: 'Mix of office and remote',
            },
        },
        interview_phase: {
            menuTitle: 'Interview phase',
            menuSubtitle: 'Which round in the interview process',
            tones: { 1: 'indigo', 2: 'violet', 3: 'cyan' },
            hints: { 1: 'First round', 2: 'Second round', 3: 'Final round' },
        },
        recommendation: {
            menuTitle: 'Recommendation',
            menuSubtitle: 'Your hiring recommendation for this candidate',
            tones: { yes: 'emerald', no: 'rose', maybe: 'amber' },
            hints: {
                yes: 'Recommend hiring',
                no: 'Do not recommend',
                maybe: 'Needs further discussion',
            },
        },
    };

    Alpine.data('choicePicker', (config = {}) => {
        const preset = CHOICE_PRESETS[config.preset] || {};
        const tones = { ...(preset.tones || {}), ...(config.tones || {}) };
        const hints = { ...(preset.hints || {}), ...(config.hints || {}) };

        return {
            open: false,
            name: config.name || '',
            value: config.value ?? '',
            options: config.options || [],
            placeholder: config.placeholder || '',
            showMenuHeader: config.showMenuHeader === true,
            menuTitle: config.menuTitle || preset.menuTitle || '',
            menuSubtitle: config.menuSubtitle || preset.menuSubtitle || '',
            ariaLabel: config.ariaLabel || 'Select option',

            tone(v) {
                if (!v) return 'zinc';
                return tones[v] || 'zinc';
            },

            hint(v) {
                if (!v) return '';
                return hints[v] || '';
            },

            labelFor(v) {
                const o = this.options.find((x) => x.value === v);
                if (o) return o.label;
                if (!v && this.placeholder) return this.placeholder;
                const empty = this.options.find((x) => x.value === '');
                if (!v && empty) return empty.label;
                return this.placeholder || 'Select…';
            },

            listOptions() {
                return this.options.filter((o) => o.value !== '');
            },

            allowsClear() {
                return this.options.some((o) => o.value === '');
            },

            pick(v) {
                this.value = v;
                this.open = false;
            },

            clear() {
                this.value = '';
                this.open = false;
            },
        };
    });

    Alpine.data('statusPickerForm', (config = {}) => ({
        open: false,
        initial: config.initial || 'new',
        value: config.initial || 'new',
        options: config.options || [],

        // Options may carry their own tone/hint (see Resume.recruiter_status_options);
        // the maps below are the fallback and mirror the model.
        tone(v) {
            const o = this.options.find((x) => x.value === v);
            if (o && o.tone) return o.tone;
            return ({
                new: 'zinc', shortlisted: 'sky', phone_screen: 'cyan', assessment: 'cyan',
                interviewing: 'indigo', selected: 'indigo', info_received: 'violet',
                bgv_completed: 'violet', offer_extended: 'violet', pre_onboarding: 'emerald',
                hired: 'emerald', rejected: 'rose', withdrawn: 'amber',
            })[v] || 'zinc';
        },

        hint(v) {
            const o = this.options.find((x) => x.value === v);
            if (o && o.hint) return o.hint;
            return ({
                new: 'Recently added to pipeline',
                shortlisted: 'Passed initial screening',
                phone_screen: 'Phone screening call',
                assessment: 'Sends the assessment link',
                interviewing: 'Interview process under way',
                selected: 'Sends the information form',
                info_received: 'Information form submitted',
                bgv_completed: 'HR verification signed off',
                offer_extended: 'Offer letter issued',
                pre_onboarding: 'Joining checklist in progress',
                hired: 'Joined the company',
                rejected: 'Not proceeding',
                withdrawn: 'Candidate withdrew',
            })[v] || '';
        },

        isOutcome(v) {
            return ['hired', 'rejected', 'withdrawn'].includes(v);
        },

        labelFor(v) {
            const o = this.options.find((x) => x.value === v);
            return o ? o.label : 'Select status';
        },

        pick(v) {
            this.value = v;
            this.open = false;
        },

        get dirty() {
            return this.value !== this.initial;
        },
    }));

    // The dashboard's job filter (core/dashboard.html). Picking a job writes the
    // hidden field and fires the change the form's hx-trigger listens for.
    Alpine.data('dashJob', (value = '', label = 'All jobs', status = '') => ({
        open: false,
        value,
        label,
        status,
        q: '',
        none: false,

        visible() {
            return Array.from(this.$refs.list.querySelectorAll('[role=option]'))
                .filter((el) => el.style.display !== 'none');
        },
        matches(title) {
            return !this.q || title.includes(this.q.trim().toLowerCase());
        },
        highlight(i) {
            this.$nextTick(() => {
                const items = this.visible();
                this.none = !items.length;
                items.forEach((el, n) => el.classList.toggle('is-active', n === i));
                if (items[i]) items[i].scrollIntoView({ block: 'nearest' });
            });
        },
        move(step) {
            const items = this.visible();
            if (!items.length) return;
            const at = items.findIndex((el) => el.classList.contains('is-active'));
            this.highlight((at + step + items.length) % items.length);
        },
        pickActive() {
            const el = this.visible().find((item) => item.classList.contains('is-active'));
            if (el) this.pick(el);
        },
        show() {
            this.open = true;
            this.q = '';
            this.$nextTick(() => {
                const items = this.visible();
                this.highlight(Math.max(0, items.findIndex((el) => el.dataset.value === this.value)));
                this.$refs.q.focus();
            });
        },
        toggle() {
            if (this.open) this.close(true); else this.show();
        },
        close(refocus) {
            if (!this.open) return;
            this.open = false;
            if (refocus) this.$nextTick(() => this.$root.querySelector('.dash-jobpick__trigger').focus());
        },
        pick(el) {
            const changed = el.dataset.value !== this.value;
            this.value = el.dataset.value;
            this.label = el.dataset.title;
            this.status = el.dataset.status;
            this.close(true);
            if (!changed) return;
            this.$refs.field.value = this.value;
            this.$refs.field.dispatchEvent(new Event('change', { bubbles: true }));
        },
    }));
});
