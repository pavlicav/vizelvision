' VizelVision Roku App
' Launches straight into the VizelVision master HLS feed.

sub Main()
    streamUrl = "http://10.0.0.98:6970/v1/master/media/index.m3u8"

    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.setMessagePort(port)
    scene = screen.CreateScene("MainScene")
    screen.show()
    scene.streamUrl = streamUrl
    while true
        msg = wait(0, port)
        if type(msg) = "roSGScreenEvent"
            if msg.isScreenClosed() then return
        end if
    end while
end sub
