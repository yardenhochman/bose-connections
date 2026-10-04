#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <CoreBluetooth/CoreBluetooth.h>
@interface App : NSObject <NSApplicationDelegate,CBCentralManagerDelegate,NSMenuDelegate>
@property NSTask *server;
@property NSWindow *window;
@property WKWebView *web;
@property CBCentralManager *bluetooth;
@property BOOL background;
@property NSStatusItem *statusItem;
@property NSMenu *deviceMenu;
@property NSDictionary *snapshot;
@property NSString *menuMessage;
@property BOOL refreshing;
@property BOOL changing;

@end
@implementation App
- (void)applicationDidFinishLaunching:(NSNotification *)note {
 NSDictionary *info=[[NSBundle mainBundle] infoDictionary];
 self.bluetooth=[[CBCentralManager alloc] initWithDelegate:self queue:nil options:@{CBCentralManagerOptionShowPowerAlertKey:@NO}];
 self.server=[[NSTask alloc] init];self.server.executableURL=[NSURL fileURLWithPath:info[@"BosePython"]];self.server.arguments=@[info[@"BoseController"],@"--config",info[@"BoseConfig"]];
 NSMutableDictionary *environment=[[[NSProcessInfo processInfo] environment] mutableCopy];environment[@"BOSE_PARENT_PID"]=[NSString stringWithFormat:@"%d",getpid()];self.server.environment=environment;
 self.server.terminationHandler=^(NSTask *task){dispatch_async(dispatch_get_main_queue(),^{[NSApp terminate:nil];});};
 NSString *dir=[info[@"BoseConfig"] stringByDeletingLastPathComponent];
 for(NSString *name in @[@"service.log",@"service-error.log"]){NSString *path=[dir stringByAppendingPathComponent:name];if(![[NSFileManager defaultManager] fileExistsAtPath:path])[[NSFileManager defaultManager] createFileAtPath:path contents:nil attributes:@{NSFilePosixPermissions:@0600}];}
 NSFileHandle *out=[NSFileHandle fileHandleForWritingAtPath:[dir stringByAppendingPathComponent:@"service.log"]];[out seekToEndOfFile];self.server.standardOutput=out;
 NSFileHandle *err=[NSFileHandle fileHandleForWritingAtPath:[dir stringByAppendingPathComponent:@"service-error.log"]];[err seekToEndOfFile];self.server.standardError=err;
 NSError *error=nil;if(![self.server launchAndReturnError:&error])NSLog(@"Could not start Bose helper: %@",error.localizedDescription);
 self.statusItem=[[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
 NSImage *icon=[NSImage imageWithSystemSymbolName:@"headphones" accessibilityDescription:@"Bose Connections"];icon.template=YES;self.statusItem.button.image=icon;self.statusItem.button.toolTip=@"Bose 700 connections";
 self.deviceMenu=[NSMenu new];self.deviceMenu.autoenablesItems=NO;self.deviceMenu.delegate=self;self.statusItem.menu=self.deviceMenu;
 NSData *cached=[NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:@"snapshot.json"]];
 if(cached)self.snapshot=[NSJSONSerialization JSONObjectWithData:cached options:0 error:nil];
 [self rebuildMenu];dispatch_after(dispatch_time(DISPATCH_TIME_NOW,3*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self refreshMenu];});
 if(!self.background)[self showWindow];
}
- (NSMenuItem *)item:(NSString *)title selector:(SEL)selector data:(id)data {
 NSMenuItem *item=[[NSMenuItem alloc] initWithTitle:title action:selector keyEquivalent:@""];item.target=self;item.representedObject=data;item.enabled=selector!=NULL && !self.changing;return item;
}
- (NSString *)label:(NSDictionary *)device {
 NSDictionary *labels=@{@"pc":@"Living-room PC",@"phone":@"Phone",@"mac":@"Mac"};
 for(NSString *role in self.snapshot[@"roles"])if([self.snapshot[@"roles"][role] isEqual:device[@"address"]])return labels[role]?:device[@"name"];
 return device[@"name"]?:device[@"address"];
}
- (void)rebuildMenu {
 [self.deviceMenu removeAllItems];
 [self.deviceMenu addItem:[self item:@"Bose 700" selector:NULL data:nil]];
 NSString *status=self.changing?@"Updating connections…":self.refreshing?@"Refreshing…":self.menuMessage;
 if(!status && self.snapshot[@"observed"]){NSDateFormatter *f=[NSDateFormatter new];f.timeStyle=NSDateFormatterShortStyle;status=[@"Updated " stringByAppendingString:[f stringFromDate:[NSDate dateWithTimeIntervalSince1970:[self.snapshot[@"observed"] doubleValue]]]];}
 if(!status)status=[self.snapshot[@"reachable"] boolValue]?@"Select a device":@"Headset unavailable";
 [self.deviceMenu addItem:[self item:status selector:NULL data:nil]];
 [self.deviceMenu addItem:[NSMenuItem separatorItem]];
 NSArray *devices=self.snapshot[@"devices"]?:@[];
 NSMutableArray *connected=[NSMutableArray new];for(NSDictionary *d in devices)if([d[@"connected"] boolValue])[connected addObject:d];
 for(NSDictionary *d in devices){
  BOOL on=[d[@"connected"] boolValue];NSString *name=[self label:d];NSDictionary *action=@{@"action":on?@"disconnect":@"connect",@"address":d[@"address"]};
  NSMenuItem *row=[self item:name selector:@selector(deviceClicked:) data:action];row.state=on?NSControlStateValueOn:NSControlStateValueOff;
  row.enabled=[self.snapshot[@"reachable"] boolValue]&&!self.changing;
  if(!on && connected.count>=2){NSMenu *replace=[NSMenu new];replace.autoenablesItems=NO;
   [replace addItem:[self item:@"Disconnect to connect:" selector:NULL data:nil]];
   for(NSDictionary *old in connected){NSMutableDictionary *a=[action mutableCopy];a[@"replace"]=old[@"address"];[replace addItem:[self item:[self label:old] selector:@selector(deviceClicked:) data:a]];}row.submenu=replace;
  }
  [self.deviceMenu addItem:row];
 }
 [self.deviceMenu addItem:[NSMenuItem separatorItem]];
 [self.deviceMenu addItem:[self item:@"Refresh" selector:@selector(refreshClicked:) data:nil]];
 [self.deviceMenu addItem:[self item:@"Open dashboard…" selector:@selector(openDashboard:) data:nil]];
}
- (void)request:(NSString *)path data:(NSDictionary *)data completion:(void (^)(NSDictionary *,NSString *))completion {
 NSMutableURLRequest *r=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:[@"http://127.0.0.1:8847" stringByAppendingString:path]]];r.timeoutInterval=data?120:40;
 if(data){r.HTTPMethod=@"POST";[r setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];r.HTTPBody=[NSJSONSerialization dataWithJSONObject:data options:0 error:nil];}
 [[[NSURLSession sharedSession] dataTaskWithRequest:r completionHandler:^(NSData *raw,NSURLResponse *response,NSError *error){
  NSDictionary *json=raw?[NSJSONSerialization JSONObjectWithData:raw options:0 error:nil]:nil;
  NSString *failure=error.localizedDescription?:json[@"error"];if(!json&&!failure)failure=@"Controller unavailable";
  dispatch_async(dispatch_get_main_queue(),^{completion(json,failure);});
 }] resume];
}
- (void)refreshMenu {
 if(self.refreshing||self.changing)return;self.refreshing=YES;[self rebuildMenu];
 [self request:@"/api/overview" data:nil completion:^(NSDictionary *json,NSString *error){self.refreshing=NO;self.snapshot=error?nil:json;self.menuMessage=error;[self rebuildMenu];}];
}
- (void)menuWillOpen:(NSMenu *)menu {[self refreshMenu];}
- (void)refreshClicked:(id)sender {[self refreshMenu];}
- (void)openDashboard:(id)sender {[self showWindow];}
- (void)deviceClicked:(NSMenuItem *)sender {
 if(self.changing)return;NSDictionary *data=[sender.representedObject copy];self.changing=YES;self.menuMessage=nil;[self rebuildMenu];
 [self request:@"/api/override" data:data completion:^(NSDictionary *json,NSString *error){
  self.changing=NO;self.menuMessage=error?:([json[@"verified"] boolValue]?@"Connection updated":@"Change not verified");
  [self rebuildMenu];[self refreshMenu];
 }];
}
- (void)centralManagerDidUpdateState:(CBCentralManager *)central {}
- (void)showWindow {
 if(!self.window){self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,1000,830) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];self.window.title=@"Bose Connections";self.web=[[WKWebView alloc] initWithFrame:self.window.contentView.bounds];self.web.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;self.window.contentView=self.web;[self.window center];
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self.web loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1:8847"]]];});}
 [self.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)flag {[self showWindow];return YES;}
- (void)applicationWillTerminate:(NSNotification *)note {if(self.server.running)[self.server terminate];}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app {return NO;}
@end
int main(int argc,const char *argv[]){@autoreleasepool{NSApplication *app=[NSApplication sharedApplication];[app setActivationPolicy:NSApplicationActivationPolicyAccessory];App *delegate=[App new];delegate.background=argc>1&&strcmp(argv[1],"--background")==0;app.delegate=delegate;[app run];}return 0;}
