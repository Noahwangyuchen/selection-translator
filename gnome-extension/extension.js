import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Pango from 'gi://Pango';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const TranslatorIndicator = GObject.registerClass(
class TranslatorIndicator extends PanelMenu.Button {
    _init(paths) {
        super._init(0.0, 'Selection Translator', false);
        this._paths = paths;
        this._state = {};

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        box.add_child(new St.Icon({
            icon_name: 'accessories-dictionary-symbolic',
            style_class: 'system-status-icon',
        }));
        this._label = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'selection-translator-panel-label',
        });
        this._label.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        this._label.clutter_text.single_line_mode = true;
        box.add_child(this._label);
        this.add_child(box);

        this._title = new PopupMenu.PopupMenuItem('划词翻译', {reactive: false});
        this._phonetic = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._translation = new PopupMenu.PopupMenuItem('请选择英文单词', {reactive: false});
        this._definition = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._engine = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._translateSentence = new PopupMenu.PopupMenuItem('翻译整句');
        this._translateWord = new PopupMenu.PopupMenuItem('在线翻译这个单词');
        this._refresh = new PopupMenu.PopupMenuItem('刷新当前选区');

        for (const item of [
            this._title,
            this._phonetic,
            this._translation,
            this._definition,
            this._engine,
        ]) {
            item.label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
            item.label.clutter_text.line_wrap = false;
        }

        for (const item of [
            this._title,
            this._phonetic,
            new PopupMenu.PopupSeparatorMenuItem(),
            this._translation,
            this._definition,
            this._engine,
            new PopupMenu.PopupSeparatorMenuItem(),
            this._translateSentence,
            this._translateWord,
            this._refresh,
        ])
            this.menu.addMenuItem(item);

        this._translateSentence.connect('activate', () => {
            const text = String(this._state.text ?? '');
            this._run(['--translate', '--text', text]);
        });
        this._translateWord.connect('activate', () => this._run(['--translate-word-current']));
        this._refresh.connect('activate', () => this._run(['--selection']));

        this._cacheDir = Gio.File.new_for_path(GLib.build_filenamev([
            GLib.get_user_cache_dir(),
            'selection-translator',
        ]));
        try {
            this._cacheDir.make_directory_with_parents(null);
        } catch (error) {
            if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
                console.error(`Selection Translator cache: ${error.message}`);
        }
        this._monitor = this._cacheDir.monitor_directory(Gio.FileMonitorFlags.NONE, null);
        this._monitorId = this._monitor.connect('changed', (_monitor, file) => {
            if (file.get_basename() === 'shared-state.json')
                this._loadState();
        });
        this._loadState();
    }

    _run(extraArgs) {
        const args = [
            this._paths.python,
            this._paths.script,
            ...extraArgs,
            '--db',
            this._paths.database,
        ];
        try {
            const process = Gio.Subprocess.new(
                args,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            process.communicate_utf8_async(null, null, (source, result) => {
                try {
                    const [, stdout, stderr] = source.communicate_utf8_finish(result);
                    if (stdout?.trim()) {
                        const lines = stdout.trim().split('\n');
                        this._apply(JSON.parse(lines[lines.length - 1]));
                    }
                    if (!source.get_successful())
                        console.error(`Selection Translator command: ${stderr}`);
                } catch (error) {
                    console.error(`Selection Translator command: ${error.message}`);
                }
            });
        } catch (error) {
            console.error(`Selection Translator launch: ${error.message}`);
        }
    }

    _loadState() {
        const stateFile = this._cacheDir.get_child('shared-state.json');
        try {
            const [ok, contents] = stateFile.load_contents(null);
            if (ok)
                this._apply(JSON.parse(new TextDecoder().decode(contents)));
        } catch (error) {
            if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                console.error(`Selection Translator state: ${error.message}`);
        }
    }

    _setItem(item, text, visible = true) {
        item.label.text = this._detailText(text);
        item.visible = visible && item.label.text.length > 0;
    }

    _displayText(text) {
        return String(text ?? '').replace(/\\n|\n/g, '  ');
    }

    _panelText(text) {
        const characters = Array.from(this._displayText(text));
        return characters.length > 36
            ? `${characters.slice(0, 36).join('')}…`
            : characters.join('');
    }

    _detailText(text, lineLength = 72) {
        const source = this._displayText(text).replace(/\s+/g, ' ').trim();
        if (!source)
            return '';

        const lines = [];
        let line = '';
        for (const originalWord of source.split(' ')) {
            let word = originalWord;
            if (line && line.length + word.length + 1 <= lineLength) {
                line += ` ${word}`;
                continue;
            }
            if (line) {
                lines.push(line);
                line = '';
            }
            while (word.length > lineLength) {
                lines.push(word.slice(0, lineLength));
                word = word.slice(lineLength);
            }
            line = word;
        }
        if (line)
            lines.push(line);
        return lines.join('\n');
    }

    _apply(state) {
        this._state = state;
        const word = state.word ?? '';
        const translated = state.translation ?? '';
        const sentenceCandidate = Boolean(state.sentenceCandidate);
        const sentenceTranslated = Boolean(state.translated) && !state.found;
        const busy = Boolean(state.translating);
        const onlineWord = state.wordOnlineTranslation ?? '';
        const message = state.message ?? '请选择英文单词';

        this._label.text = this._panelText(busy
            ? '翻译中...'
            : (sentenceTranslated ? translated : (state.found ? translated : '')));
        this._title.label.text = this._detailText(word || state.text || '划词翻译');
        this._setItem(this._phonetic, state.phonetic ? `/${state.phonetic}/` : '', Boolean(state.found));
        this._setItem(this._translation, state.found || sentenceTranslated ? translated : message, true);
        this._setItem(this._definition, state.definition ?? '', Boolean(state.found));
        this._setItem(
            this._engine,
            onlineWord ? `${onlineWord}\n${state.wordOnlineEngine ?? ''}` : (sentenceTranslated ? state.engine ?? '' : ''),
            true
        );
        this._translateSentence.visible = sentenceCandidate || busy;
        this._translateSentence.setSensitive(sentenceCandidate && !busy);
        this._translateSentence.label.text = busy ? '翻译中...' : '翻译整句';
        this._translateWord.visible = Boolean(state.found);
        this._translateWord.setSensitive(!state.wordOnlineTranslating);
        this._translateWord.label.text = state.wordOnlineTranslating ? '在线翻译中...' : '在线翻译这个单词';
    }

    destroy() {
        if (this._monitorId)
            this._monitor.disconnect(this._monitorId);
        this._monitor?.cancel();
        this._monitor = null;
        super.destroy();
    }
});

export default class SelectionTranslatorExtension extends Extension {
    enable() {
        const config = this.dir.get_child('paths.json');
        const [ok, contents] = config.load_contents(null);
        if (!ok)
            throw new Error('Selection Translator paths.json is unavailable');
        const paths = JSON.parse(new TextDecoder().decode(contents));
        this._indicator = new TranslatorIndicator(paths);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
