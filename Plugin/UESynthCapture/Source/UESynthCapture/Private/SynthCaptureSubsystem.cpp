#include "SynthCaptureSubsystem.h"
#include "SynthVehicleAnnotator.h"
#include "SynthCOCOExporter.h"

DEFINE_LOG_CATEGORY_STATIC(LogSynthCapture, Log, All);

void USynthCaptureSubsystem::BeginCaptureSession(const FCaptureSessionConfig& Config)
{
    if (bSessionActive)
    {
        UE_LOG(LogSynthCapture, Warning, TEXT("BeginCaptureSession called while session active. Ending previous."));
        EndCaptureSession();
    }
    ActiveConfig = Config;
    bSessionActive = true;
    NextImageId = 1;
    NextAnnotationId = 1;

    const FString OutPath = FPaths::Combine(ActiveConfig.OutputDirectory, TEXT("annotations"), TEXT("coco.json"));
    Exporter = MakeUnique<FSynthCOCOExporter>(OutPath, ActiveConfig.DatasetName);
    Exporter->Begin();

    UE_LOG(LogSynthCapture, Log, TEXT("Capture session '%s' started, output=%s"),
        *ActiveConfig.SessionId, *ActiveConfig.OutputDirectory);
}

void USynthCaptureSubsystem::EndCaptureSession()
{
    if (!bSessionActive)
    {
        return;
    }
    if (Exporter.IsValid())
    {
        Exporter->End();
        Exporter.Reset();
    }
    bSessionActive = false;
    UE_LOG(LogSynthCapture, Log, TEXT("Capture session ended."));
}

void USynthCaptureSubsystem::CaptureFrame(int32 FrameId)
{
    if (!bSessionActive)
    {
        UE_LOG(LogSynthCapture, Error, TEXT("CaptureFrame called without active session."));
        return;
    }

    // Phase 0: single camera path filled in by Task 12 (after annotator + projection implemented).
    // For now this is a stub that increments IDs so we can wire up the test scaffold.
    UE_LOG(LogSynthCapture, Verbose, TEXT("CaptureFrame %d (stub)"), FrameId);
}

void USynthCaptureSubsystem::RegisterAnnotator(USynthVehicleAnnotator* Annotator)
{
    if (Annotator)
    {
        Annotators.AddUnique(Annotator);
    }
}

void USynthCaptureSubsystem::UnregisterAnnotator(USynthVehicleAnnotator* Annotator)
{
    Annotators.RemoveAll([Annotator](const TWeakObjectPtr<USynthVehicleAnnotator>& W)
    {
        return W.Get() == Annotator;
    });
}
