#!/usr/bin/perl
# RAW 归档 v1.0.0 —— DSM CGI 入口
use strict; use warnings; use utf8;
use CGI; use JSON::PP; use Cwd qw(realpath);
binmode STDOUT, ':utf8';

my $q = CGI->new;
my $APP_NAME = 'RAW 归档';
my $APP_VER  = '1.0.0';

# 三个路径由 installer.sh 写入 env 文件；也允许环境变量覆盖
my $HOME_DIR = $ENV{RAWARCHIVER_HOME} || '/volume1/web/rawarchiver';
if (open my $ef, '<', "$HOME_DIR/etc/env") { my $l = <$ef>; close $ef; chomp $l; $HOME_DIR = $l if $l; }
my $PY     = $ENV{RAWARCHIVER_PY}    || "$HOME_DIR/agent/venv/bin/python3";
$PY        = '/usr/bin/python3' unless -x $PY;
my $SCRIPT = "$HOME_DIR/scripts/raw_archiver.py";
my $DATA   = "$HOME_DIR/data/rawarchiver";

print $q->header(-type => 'application/json; charset=UTF-8');

sub err { print encode_json({ok=>0, error=>$_[0]}); exit 0; }
sub okj { print encode_json({ok=>1, @_}); exit 0; }

sub safe {
    my $p = shift // '';
    $p =~ s{^/+}{/};
    err("路径不合法：必须以 /volume 开头且不含 ..") unless $p =~ m{^/volume} && $p !~ /\.\./;
    return $p;
}
sub inside {
    my ($c, $p) = @_;
    return 0 unless $c && $p;
    $c = realpath($c) // ''; $p = realpath($p) // '';
    return ($c eq $p || $c =~ m{^\Q$p\E/}) ? 1 : 0;
}
sub task_dir { my ($id, $out) = @_; $out ? "$out/.rawarchiver/tasks/$id" : "$DATA/tasks/$id" }
sub load_state {
    my ($id, $out) = @_;
    my $sp = task_dir($id, $out) . '/state.json';
    return undef unless -f $sp;
    open my $fh, '<:utf8', $sp or return undef; my $s = do { local $/; <$fh> }; close $fh;
    my $j = eval { decode_json($s) }; return $j;
}
sub run_py {
    my @a = ($PY, '-X', 'utf8', $SCRIPT, @_);
    my $out = `@a 2>&1`;
    return $out;
}
sub jargs {
    my $p = shift; my @a;
    push @a, '--brand'     if $p->{brandFolder};
    push @a, '--no-jpg'    unless !defined $p->{handleJpg}  || $p->{handleJpg};
    push @a, '--no-video'  unless !defined $p->{handleVideo}|| $p->{handleVideo};
    push @a, '--month'     if $p->{monthDir};
    push @a, ($p->{staging} // 1) ? '--staging' : '--no-staging';
    return @a;
}

my $body = do { local $/; <STDIN> };
my $p = ($body && length $body) ? (eval { decode_json($body) } || {}) : {};
my $act = $p->{action} || $q->param('action') || 'info';

if ($act eq 'info') {
    okj(app=>$APP_NAME, version=>$APP_VER, script=>$SCRIPT, python=>$PY,
        exiftool=>(-f "$HOME_DIR/vendor/exiftool/exiftool" ? 1 : 0));
}
elsif ($act eq 'doctor') {
    okj(result=> eval { decode_json(run_py('--doctor')) } || {});
}
elsif ($act eq 'devices') {
    my @list;
    for my $d (glob('/volumeUSB*/usbshare* /volumeUSB*/usbshare')) {
        next unless -d $d;
        my $lab = `synosetkeyvalue 2>/dev/null`;   # 占位，卷标读不到则留空
        my $n = `find "$d" -maxdepth 5 -type f \\( -iname '*.nef' -o -iname '*.cr2' -o -iname '*.cr3' -o -iname '*.arw' -o -iname '*.raf' -o -iname '*.orf' -o -iname '*.dng' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mts' \\) 2>/dev/null | wc -l`;
        chomp $n;
        my ($vol) = $d =~ m{^(/volumeUSB\d+)};
        my $sz = `df -k "$vol" 2>/dev/null | awk 'NR==2{print \$2}'`; chomp $sz;
        push @list, {path=>$d, label=>'', files=>$n + 0, total_kb=>($sz // 0) + 0};
    }
    okj(list=>\@list);
}
elsif ($act eq 'mkdir') {
    my $path = safe($p->{path});
    mkpath_of($path);
    okj(path=>$path);
}
elsif ($act eq 'preview') {
    err('source 必填') unless $p->{source};
    my $out = safe($p->{output});
    my $r = run_py($p->{source}, '--output', $out, '--preview', jargs($p));
    my $j = eval { decode_json($r) };
    err("预览失败: " . substr($r, 0, 800)) unless $j;
    okj(result=>$j);
}
elsif ($act eq 'start') {
    err('source 与 output 必填') unless $p->{source} && $p->{output};
    my $out = safe($p->{output});
    err('输出目录不能位于源目录内部') if inside($out, $p->{source});
    err('源目录不存在') unless -d $p->{source};
    mkpath_of("$out/.rawarchiver/tasks");
    my $tid = $p->{taskId} || do { my @t = localtime(); sprintf('%04d%02d%02d_%02d%02d%02d', $t[5]+1900, $t[4]+1, $t[3], $t[2], $t[1], $t[0]) . '_' . int(rand(900)+100) };
    my @a = ($PY, '-X', 'utf8', $SCRIPT, $p->{source}, '--output', $out,
             '--mode', ($p->{mode} && $p->{mode} eq 'move' ? 'move' : 'copy'),
             '--task-id', $tid, jargs($p));
    my $cmd = join(' ', map { "'$_'" } @a);
    # 后台分离执行，CGI 立即返回
    system("/bin/sh -c \"nohup $cmd > '$out/.rawarchiver/tasks/$tid/run.log' 2>&1 &\"");
    okj(taskId=>$tid);
}
elsif ($act eq 'status') {
    err('id 必填') unless $p->{id};
    my $st = load_state($p->{id}, $p->{output} ? safe($p->{output}) : '');
    err('任务不存在') unless $st;
    $st->{logs} = [ @{$st->{logs} || []} ];
    $st->{logs} = [ @{$st->{logs}}[ -80 .. -1 ] ] if @{$st->{logs}} > 80;
    delete $st->{done}; delete $st->{to_delete};
    okj(state=>$st);
}
elsif ($act eq 'cancel') {
    my $td = task_dir($p->{taskId}, $p->{output} ? safe($p->{output}) : '');
    err('任务不存在') unless -d $td;
    open my $fh, '>', "$td/cancel"; close $fh;
    okj();
}
elsif ($act eq 'cleanup') {
    my $out = safe($p->{output});
    err('taskId 必填') unless $p->{taskId};
    my $r = run_py('--output', $out, '--task-id', $p->{taskId}, '--cleanup');
    my $j = eval { decode_json($r) };
    okj($j ? %$j : (ok=>0, error=>substr($r, 0, 800)));
}
elsif ($act eq 'rollback') {
    my $out = safe($p->{output});
    err('taskId 必填') unless $p->{taskId};
    my $st = load_state($p->{taskId}, $out);
    err('移动模式不可回滚，请依靠 _report_*.json 清单') if $st && ($st->{mode} // '') eq 'move';
    my $r = run_py('--output', $out, '--task-id', $p->{taskId}, '--rollback');
    my $j = eval { decode_json($r) };
    okj($j ? %$j : (ok=>0, error=>substr($r, 0, 800)));
}
else { err("未知动作: $act") }

sub mkpath_of {
    my $path = shift;
    return if -d $path;
    my @parts = grep { length } split m{/}, $path;
    my $cur = '';
    for my $x (@parts) { $cur .= "/$x"; mkdir $cur unless -d $cur; }
}
