#import <Cocoa/Cocoa.h>

static NSString *usablePython(void) {
    NSMutableArray<NSString *> *candidates = [NSMutableArray array];
    for (NSInteger version = 16; version >= 10; --version) {
        [candidates addObject:[NSString stringWithFormat:
            @"/Library/Frameworks/Python.framework/Versions/3.%ld/bin/python3", (long)version]];
    }
    [candidates addObjectsFromArray:@[@"/opt/homebrew/bin/python3", @"/usr/local/bin/python3", @"/usr/bin/python3"]];
    for (NSString *path in candidates) {
        if (![[NSFileManager defaultManager] isExecutableFileAtPath:path]) continue;
        NSTask *test = [[NSTask alloc] init];
        test.executableURL = [NSURL fileURLWithPath:path];
        test.arguments = @[@"-c", @"import sys, tkinter; assert sys.version_info >= (3, 10)"];
        test.standardOutput = [NSFileHandle fileHandleWithNullDevice];
        test.standardError = [NSFileHandle fileHandleWithNullDevice];
        if ([test launchAndReturnError:nil]) {
            [test waitUntilExit];
            if (test.terminationStatus == 0) return path;
        }
    }
    return nil;
}

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
        [NSApp activateIgnoringOtherApps:YES];
        NSString *python = usablePython();
        if (!python) {
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"MediaTeleBot cần Python 3.10 trở lên";
            alert.informativeText = @"Cài Python cho macOS từ Python.org, sau đó mở lại MediaTeleBot.";
            [alert addButtonWithTitle:@"Mở Python.org"];
            [alert addButtonWithTitle:@"Đóng"];
            if ([alert runModal] == NSAlertFirstButtonReturn) {
                [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"https://www.python.org/downloads/macos/"]];
            }
            return 1;
        }
        NSString *script = [[NSBundle mainBundle] pathForResource:@"install_core" ofType:@"py"];
        if (!script) return 2;
        NSTask *setup = [[NSTask alloc] init];
        setup.executableURL = [NSURL fileURLWithPath:python];
        setup.arguments = @[script, @"--gui"];
        NSError *error = nil;
        if (![setup launchAndReturnError:&error]) {
            NSAlert *alert = [NSAlert alertWithError:error];
            [alert runModal];
            return 3;
        }
        [setup waitUntilExit];
        return setup.terminationStatus;
    }
}
